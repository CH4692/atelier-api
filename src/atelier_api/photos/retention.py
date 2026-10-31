"""Manage administrator-only reversible photo lifecycle transitions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.instruments.models import Instrument
from atelier_api.settings import Settings

from .models import InstrumentPhoto
from .schemas import PhotoRead, PhotoRetentionRead
from .service import get_photo
from .storage import StorageError, StorageService


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_object_identity(
    photo: InstrumentPhoto, public_id: UUID, namespace: str
) -> bool:
    """Require the exact generated instrument/UUIDv4/verified-extension key shape."""
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(
        photo.content_type
    )
    prefix = f"instruments/{public_id}/"
    if (
        photo.storage_namespace != namespace
        or not extension
        or not photo.storage_key.startswith(prefix)
    ):
        return False
    suffix = photo.storage_key[len(prefix) :]
    try:
        photo_uuid = UUID(suffix.removesuffix(f".{extension}"))
    except ValueError:
        return False
    return photo_uuid.version == 4 and suffix == f"{photo_uuid}.{extension}"


def save_transition(
    session: Session, photo: InstrumentPhoto, actor_id: int | None, action: AuditAction
) -> None:
    """Commit a lifecycle transition and its minimal audit facts atomically."""
    try:
        session.add(photo)
        record_event(
            session,
            action,
            AuditResource.INSTRUMENT_PHOTO,
            photo.id,
            actor_id=actor_id,
            details=AuditDetails(instrument_id=photo.instrument_id),
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Photo metadata unavailable") from None


def ensure_recoverable(photo: InstrumentPhoto, config: Settings) -> None:
    if photo.status != "deleted":
        raise HTTPException(409, "Only soft-deleted photographs can be restored")
    if (
        photo.deletion_requested_at is None
        or photo.deletion_requested_at
        + timedelta(days=config.photo_soft_delete_retention_days)
        <= utc_now()
    ):
        raise HTTPException(409, "Photograph recovery period has expired")


def restore_photo(
    session: Session,
    storage: StorageService,
    config: Settings,
    instrument_id: int,
    photo_id: int,
    actor_id: int | None,
) -> PhotoRead:
    """Check R2 outside a transaction, then recheck lifecycle under a row lock."""
    photo = get_photo(session, instrument_id, photo_id, include_deleted=True)
    ensure_recoverable(photo, config)
    instrument = session.get(Instrument, instrument_id)
    if instrument is None or not validate_object_identity(
        photo, instrument.public_id, storage.namespace
    ):
        raise HTTPException(409, "Photograph object identity is invalid")
    key = photo.storage_key
    session.commit()
    try:
        if not storage.exists(key):
            raise HTTPException(409, "Photograph content is missing")
    except StorageError:
        raise HTTPException(503, "Photograph storage unavailable") from None
    photo = get_photo(session, instrument_id, photo_id, include_deleted=True, lock=True)
    ensure_recoverable(photo, config)
    if photo.storage_key != key or photo.storage_namespace != storage.namespace:
        raise HTTPException(409, "Photograph object identity changed")
    photo.status = "ready"
    photo.deletion_requested_at = None
    photo.deletion_requested_by_user_id = None
    photo.purge_approved_at = None
    photo.purge_approved_by_user_id = None
    result = PhotoRead.model_validate(photo)
    save_transition(session, photo, actor_id, AuditAction.PHOTO_RESTORED)
    return result


def manage_hold(
    session: Session,
    instrument_id: int,
    photo_id: int,
    actor_id: int | None,
    reason: str | None,
) -> PhotoRetentionRead:
    """Serialize hold changes with purge claims; holds never expire implicitly."""
    photo = get_photo(session, instrument_id, photo_id, include_deleted=True, lock=True)
    if photo.status == "purging":
        raise HTTPException(409, "Photograph is being permanently deleted")
    if reason is not None and photo.retention_hold_reason is not None:
        if reason == photo.retention_hold_reason:
            return PhotoRetentionRead.model_validate(photo)
        raise HTTPException(409, "Release the existing hold before replacing it")
    if reason is None and photo.retention_hold_reason is None:
        return PhotoRetentionRead.model_validate(photo)
    photo.retention_hold_reason = reason
    photo.retention_hold_at = utc_now() if reason else None
    photo.retention_hold_by_user_id = actor_id if reason else None
    # Releasing a hold is not approval to destroy the photograph.
    photo.purge_approved_at = None
    photo.purge_approved_by_user_id = None
    result = PhotoRetentionRead.model_validate(photo)
    save_transition(
        session,
        photo,
        actor_id,
        AuditAction.PHOTO_HOLD_CREATED if reason else AuditAction.PHOTO_HOLD_RELEASED,
    )
    return result


def approve_purge(
    session: Session, instrument_id: int, photo_id: int, actor_id: int | None
) -> PhotoRetentionRead:
    """Require per-deletion review in addition to the global activation switch."""
    photo = get_photo(session, instrument_id, photo_id, include_deleted=True, lock=True)
    if photo.status != "deleted" or photo.retention_hold_reason is not None:
        raise HTTPException(
            409, "Only soft-deleted photographs without a hold can be approved"
        )
    if photo.purge_approved_at is None:
        photo.purge_approved_at = utc_now()
        photo.purge_approved_by_user_id = actor_id
        result = PhotoRetentionRead.model_validate(photo)
        save_transition(session, photo, actor_id, AuditAction.PHOTO_PURGE_APPROVED)
        return result
    return PhotoRetentionRead.model_validate(photo)
