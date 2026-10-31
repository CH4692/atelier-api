"""Coordinate PostgreSQL intents with nontransactional private object writes."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.instruments.models import Instrument

from .images import PreparedImage
from .models import InstrumentPhoto
from .schemas import PhotoRead
from .storage import ObjectConflict, StorageError, StorageService

logger = logging.getLogger(__name__)


def require_instrument(session: Session, instrument_id: int) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    return instrument


def get_photo(
    session: Session,
    instrument_id: int,
    photo_id: int,
    *,
    include_deleted: bool = False,
    lock: bool = False,
) -> InstrumentPhoto:
    statement = select(InstrumentPhoto).where(
        InstrumentPhoto.id == photo_id,
        InstrumentPhoto.instrument_id == instrument_id,
        col(InstrumentPhoto.status).in_(["ready", "deleted", "purging"]),
    )
    if not include_deleted:
        statement = statement.where(InstrumentPhoto.status == "ready")
    if lock:
        statement = statement.with_for_update()
    photo = session.exec(statement).first()
    if photo is None:
        raise HTTPException(404, "Photograph not found")
    return photo


def remove_pending(
    session: Session,
    storage: StorageService,
    *,
    ids: list[int] | None = None,
    cutoff: datetime | None = None,
    skip_keys: set[str] | None = None,
) -> int:
    """Retry idempotent compensation; retain intent whenever object deletion fails.

    Row locks prevent cleaning an active upload. Only pending intents are eligible;
    ready and soft-deleted evidence is never permanently removed by this command.
    """
    statement = select(InstrumentPhoto).where(
        InstrumentPhoto.status == "pending",
        InstrumentPhoto.storage_namespace == storage.namespace,
    )
    if ids is not None:
        statement = statement.where(col(InstrumentPhoto.id).in_(ids))
    if cutoff is not None:
        statement = statement.where(InstrumentPhoto.uploaded_at < cutoff)
    pending = session.exec(
        statement.order_by(col(InstrumentPhoto.id))
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    removed = 0
    for photo in pending:
        try:
            if photo.storage_key not in (skip_keys or set()):
                storage.delete(photo.storage_key)
        except StorageError:
            logger.warning("Photo upload compensation requires retry")
            continue
        session.delete(photo)
        removed += 1
    session.commit()
    return removed


def cleanup_abandoned_uploads(session: Session, storage: StorageService) -> int:
    """Clean at most 100 abandoned intents older than one operational day."""
    return remove_pending(
        session, storage, cutoff=datetime.now(UTC) - timedelta(hours=24)
    )


def upload_photos(
    session: Session,
    storage: StorageService,
    instrument_id: int,
    actor_id: int,
    images: list[PreparedImage],
) -> list[PhotoRead]:
    """Publish a whole batch or leave no visible photos from that batch.

    Persist intents before touching R2. Keep their row locks during object writes
    and the final audit/metadata commit. Crashes and unavailable cleanup leave
    durable keys for the operator cleanup command, never untracked objects.
    """
    instrument = require_instrument(session, instrument_id)
    records = [
        InstrumentPhoto(
            instrument_id=instrument_id,
            storage_namespace=storage.namespace,
            storage_key=f"instruments/{instrument.public_id}/{uuid4()}.{image.extension}",
            original_filename=image.filename,
            content_type=image.content_type,
            file_size_bytes=image.size,
            uploaded_by_user_id=actor_id,
        )
        for image in images
    ]
    try:
        session.add_all(records)
        session.flush()
        ids = [photo.id for photo in records if photo.id is not None]
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Photo metadata unavailable") from None
    conflict_keys: set[str] = set()
    try:
        locked = session.exec(
            select(InstrumentPhoto)
            .where(
                col(InstrumentPhoto.id).in_(ids), InstrumentPhoto.status == "pending"
            )
            .order_by(col(InstrumentPhoto.id))
            .with_for_update()
        ).all()
        if len(locked) != len(images):
            raise StorageError
        for photo, image in zip(locked, images, strict=True):
            try:
                storage.upload(
                    photo.storage_key, image.source, image.size, image.content_type
                )
            except ObjectConflict:
                # A conditional-write collision must not delete the existing object.
                conflict_keys.add(photo.storage_key)
                raise
            photo.status = "ready"
            session.add(photo)
            record_event(
                session,
                AuditAction.PHOTO_UPLOADED,
                AuditResource.INSTRUMENT_PHOTO,
                photo.id,
                actor_id=actor_id,
                details=AuditDetails(instrument_id=instrument_id),
            )
        result = [PhotoRead.model_validate(photo) for photo in locked]
        session.commit()
        return result
    except StorageError, SQLAlchemyError:
        session.rollback()
        try:
            # If commit succeeded but acknowledgement failed, ready rows are retained.
            remove_pending(session, storage, ids=ids, skip_keys=conflict_keys)
        except SQLAlchemyError:
            session.rollback()
            logger.warning("Photo upload intents require later reconciliation")
        raise HTTPException(503, "Photograph upload failed") from None
