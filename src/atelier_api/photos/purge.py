"""Purge reviewed photos using durable claims and PostgreSQL session locks."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from uuid import uuid4

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.instruments.models import Instrument
from atelier_api.settings import Settings

from .models import InstrumentPhoto
from .retention import utc_now, validate_object_identity
from .storage import StorageError, StorageService

logger = logging.getLogger(__name__)
_LOCK_NAMESPACE = 1096044616
_KEY_VALID = """p.storage_key ~ (
    '^instruments/' || i.public_id::text ||
    '/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}' ||
    CASE p.content_type WHEN 'image/jpeg' THEN '\\.jpg$'
                        WHEN 'image/png' THEN '\\.png$'
                        WHEN 'image/webp' THEN '\\.webp$' ELSE 'INVALID$' END
)"""
_ELIGIBLE = """(p.status = 'purging' OR (p.status = 'deleted' AND p.deletion_requested_at <= :cutoff))
    AND p.retention_hold_reason IS NULL AND p.purge_approved_at IS NOT NULL
    AND (CAST(:namespace AS text) IS NULL OR p.storage_namespace = :namespace)"""


@dataclass
class PurgeSummary:
    """Report aggregate lifecycle facts without filenames, keys or credentials."""

    execution_id: str
    dry_run: bool = False
    storage_configured: bool = False
    eligible: int = 0
    eligible_bytes: int = 0
    protected: int = 0
    unreviewed: int = 0
    young: int = 0
    active: int = 0
    interrupted: int = 0
    invalid_identity: int = 0
    wrong_storage: int = 0
    processed: int = 0
    purged: int = 0
    skipped: int = 0
    failed: int = 0
    recovered_claims: int = 0
    bytes_freed: int = 0
    duration_seconds: float = 0
    result: str = "success"


@dataclass(frozen=True)
class PurgeClaim:
    photo_id: int
    instrument_id: int
    key: str
    size: int
    recovered: bool


def retention_statistics(
    session: Session, config: Settings, namespace: str | None, now: datetime
) -> PurgeSummary:
    """Read aggregate statistics without locking, auditing or touching storage.

    Without configured storage this reports potential eligibility across storage
    locations. Destructive execution always requires one exact configured location.
    """
    statement = text(f"""
        SELECT
          count(*) FILTER (WHERE {_ELIGIBLE} AND {_KEY_VALID}) AS eligible,
          coalesce(sum(p.file_size_bytes) FILTER (WHERE {_ELIGIBLE} AND {_KEY_VALID}), 0) AS eligible_bytes,
          count(*) FILTER (WHERE p.status = 'deleted' AND p.deletion_requested_at <= :cutoff AND p.retention_hold_reason IS NOT NULL) AS protected,
          count(*) FILTER (WHERE p.status = 'deleted' AND p.deletion_requested_at <= :cutoff AND p.purge_approved_at IS NULL AND p.retention_hold_reason IS NULL) AS unreviewed,
          count(*) FILTER (WHERE p.status = 'deleted' AND p.deletion_requested_at > :cutoff) AS young,
          count(*) FILTER (WHERE p.status = 'ready') AS active,
          count(*) FILTER (WHERE p.status = 'purging') AS interrupted,
          count(*) FILTER (WHERE {_ELIGIBLE} AND NOT ({_KEY_VALID})) AS invalid_identity,
          count(*) FILTER (WHERE (p.status = 'purging' OR (p.status = 'deleted' AND p.deletion_requested_at <= :cutoff)) AND CAST(:namespace AS text) IS NOT NULL AND p.storage_namespace <> :namespace) AS wrong_storage
        FROM instrument_photo p JOIN instrument i ON i.id = p.instrument_id
    """)
    row = (
        session.execute(
            statement,
            {
                "cutoff": now - timedelta(days=config.photo_soft_delete_retention_days),
                "namespace": namespace,
            },
        )
        .mappings()
        .one()
    )
    return PurgeSummary(
        execution_id=str(uuid4()),
        storage_configured=namespace is not None,
        eligible=int(row["eligible"]),
        eligible_bytes=int(row["eligible_bytes"]),
        protected=int(row["protected"]),
        unreviewed=int(row["unreviewed"]),
        young=int(row["young"]),
        active=int(row["active"]),
        interrupted=int(row["interrupted"]),
        invalid_identity=int(row["invalid_identity"]),
        wrong_storage=int(row["wrong_storage"]),
    )


def claim_photo(
    session: Session,
    storage: StorageService,
    config: Settings,
    photo_id: int,
    execution_id: str,
    now: datetime,
) -> PurgeClaim | None:
    """Commit a non-restorable state before issuing any external deletion."""
    photo = session.exec(
        select(InstrumentPhoto)
        .where(InstrumentPhoto.id == photo_id)
        .with_for_update(skip_locked=True)
    ).first()
    if photo is None:
        session.rollback()
        return None
    recovered = photo.status == "purging"
    if not recovered and (
        photo.status != "deleted"
        or photo.deletion_requested_at is None
        or photo.deletion_requested_at
        > now - timedelta(days=config.photo_soft_delete_retention_days)
    ):
        session.rollback()
        return None
    instrument = session.get(Instrument, photo.instrument_id)
    if (
        photo.retention_hold_reason is not None
        or photo.purge_approved_at is None
        or instrument is None
        or not validate_object_identity(photo, instrument.public_id, storage.namespace)
    ):
        session.rollback()
        return None
    if not recovered:
        photo.status = "purging"
        session.add(photo)
        record_event(
            session,
            AuditAction.PHOTO_PURGE_STARTED,
            AuditResource.INSTRUMENT_PHOTO,
            photo.id,
            details=AuditDetails(
                instrument_id=photo.instrument_id, execution_id=execution_id
            ),
        )
    claim = PurgeClaim(
        photo_id,
        photo.instrument_id,
        photo.storage_key,
        photo.file_size_bytes,
        recovered,
    )
    session.commit()
    return claim


def finalize_purge(session: Session, claim: PurgeClaim, execution_id: str) -> bool:
    """Remove personal metadata and append one audit event in the same commit."""
    photo = session.exec(
        select(InstrumentPhoto)
        .where(InstrumentPhoto.id == claim.photo_id)
        .with_for_update()
    ).first()
    if photo is None:
        session.rollback()
        return False
    if photo.status != "purging" or photo.storage_key != claim.key:
        raise StorageError("Purge claim changed")
    record_event(
        session,
        AuditAction.PHOTO_PURGED,
        AuditResource.INSTRUMENT_PHOTO,
        claim.photo_id,
        details=AuditDetails(
            instrument_id=claim.instrument_id, execution_id=execution_id
        ),
    )
    session.delete(photo)
    session.commit()
    return True


def record_failure(session: Session, photo_id: int, execution_id: str) -> None:
    """Record a sanitized failed attempt while preserving the irreversible state."""
    session.rollback()
    try:
        photo = session.get(InstrumentPhoto, photo_id)
        if photo is not None and photo.status == "purging":
            record_event(
                session,
                AuditAction.PHOTO_PURGE_FAILED,
                AuditResource.INSTRUMENT_PHOTO,
                photo_id,
                succeeded=False,
                details=AuditDetails(
                    instrument_id=photo.instrument_id, execution_id=execution_id
                ),
            )
            session.commit()
        else:
            session.rollback()
    except SQLAlchemyError:
        session.rollback()
        logger.error(
            "Photo purge failure could not be audited",
            extra={"execution_id": execution_id, "photo_id": photo_id},
        )


def purge_photos(
    engine: Engine,
    storage: StorageService,
    config: Settings,
    *,
    limit: int = 100,
    now: datetime | None = None,
    execution_id: str | None = None,
) -> PurgeSummary:
    """Process bounded claims; never hold a database transaction across R2 I/O.

    A dedicated physical connection owns session-level advisory locks. Use a
    direct PostgreSQL endpoint, never a transaction-pooling proxy. A worker crash
    releases its connection lock; durable purging rows remain non-restorable and
    can be reclaimed without a lease or resetting lifecycle state.
    """
    if not config.photo_auto_purge_enabled:
        raise ValueError("Automatic photo purging is disabled")
    if not 1 <= limit <= 1000:
        raise ValueError("Purge limit must be between 1 and 1000")
    if engine.dialect.name != "postgresql":
        raise ValueError("Photo purging requires PostgreSQL")
    if "-pooler" in (engine.url.host or ""):
        raise ValueError("Photo purging requires a direct PostgreSQL endpoint")
    started = monotonic()
    now = now or utc_now()
    with engine.connect() as connection, Session(bind=connection) as session:
        summary = retention_statistics(session, config, storage.namespace, now)
        if execution_id is not None:
            summary.execution_id = execution_id
        ids = list(
            session.execute(
                text(f"""SELECT p.id FROM instrument_photo p
            JOIN instrument i ON i.id = p.instrument_id
            WHERE {_ELIGIBLE} AND {_KEY_VALID}
            ORDER BY CASE WHEN p.status = 'purging' THEN 0 ELSE 1 END,
                     p.deletion_requested_at, p.id LIMIT :limit"""),
                {
                    "cutoff": now
                    - timedelta(days=config.photo_soft_delete_retention_days),
                    "namespace": storage.namespace,
                    "limit": limit,
                },
            ).scalars()
        )
        session.commit()
        for photo_id in ids:
            acquired = False
            try:
                acquired = bool(
                    connection.scalar(
                        text("SELECT pg_try_advisory_lock(:namespace, :id)"),
                        {"namespace": _LOCK_NAMESPACE, "id": photo_id},
                    )
                )
                connection.commit()
                if not acquired:
                    summary.skipped += 1
                    continue
                claim = claim_photo(
                    session, storage, config, photo_id, summary.execution_id, now
                )
                if claim is None:
                    summary.skipped += 1
                    continue
                summary.processed += 1
                summary.recovered_claims += int(claim.recovered)
                # claim_photo committed: no transaction is open during either call.
                storage.delete(claim.key)
                if storage.exists(claim.key):
                    raise StorageError("Photograph still exists after deletion")
                if finalize_purge(session, claim, summary.execution_id):
                    summary.purged += 1
                    summary.bytes_freed += claim.size
            except StorageError, SQLAlchemyError:
                summary.failed += 1
                record_failure(session, photo_id, summary.execution_id)
                logger.warning(
                    "Photo purge attempt failed",
                    extra={"execution_id": summary.execution_id, "photo_id": photo_id},
                )
            finally:
                if acquired:
                    session.rollback()
                    try:
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:namespace, :id)"),
                            {"namespace": _LOCK_NAMESPACE, "id": photo_id},
                        )
                        connection.commit()
                    except SQLAlchemyError:
                        # Never return a connection with an uncertain session lock.
                        connection.invalidate()
                        raise
    summary.duration_seconds = round(monotonic() - started, 3)
    if summary.failed or summary.invalid_identity or summary.wrong_storage:
        summary.result = "failed"
    return summary
