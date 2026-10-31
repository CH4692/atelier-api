"""Expose authenticated photo metadata and proxied private image contents."""

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.auth.dependencies import CurrentUser, SecuritySettings
from atelier_api.database import SessionDep
from atelier_api.users.models import User
from atelier_api.users.roles import UserRole

from .images import prepare_image
from .limits import parse_photos
from .models import MAX_PHOTOS, InstrumentPhoto
from .retention import approve_purge, manage_hold, restore_photo
from .schemas import PhotoRead, PhotoRetentionRead, PurgeApproval, RetentionHoldCreate
from .service import get_photo, require_instrument, upload_photos
from .storage import ObjectMissing, StorageDep, StorageError

router = APIRouter(
    prefix="/instruments/{instrument_id}/photos",
    tags=["instrument photos"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Workshop access required"},
        404: {"description": "Instrument or photograph not found"},
        503: {"description": "Photo storage or database unavailable"},
    },
)


def require_photo_admin(user: CurrentUser) -> User:
    """Reject non-administrators before resolving optional storage dependencies."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator required")
    return user


PhotoAdmin = Annotated[User, Depends(require_photo_admin)]


@router.post(
    "",
    response_model=list[PhotoRead],
    status_code=201,
    summary="Upload up to 10 JPEG, PNG or WebP photos (10 MB each)",
    responses={
        413: {"description": "Upload limit exceeded"},
        415: {"description": "Unsupported image format"},
        422: {"description": "Invalid image or filename"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 10,
                                "items": {"type": "string", "format": "binary"},
                            }
                        },
                    }
                }
            },
        }
    },
)
async def upload(
    instrument_id: int,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> list[PhotoRead]:
    """Verify the instrument before parsing; spool bounded input and strip metadata.

    Actual image bytes determine MIME type, regardless of the declared type or
    extension. Images exceeding 20 megapixels and animated images are rejected.
    A failed batch publishes no partial photo list. Original encodings are not
    retained; JPEG/WebP re-encoding may change pixels through compression.
    """
    await run_in_threadpool(require_instrument, session, instrument_id)
    if (
        not request.headers.get("content-type", "")
        .lower()
        .startswith("multipart/form-data")
    ):
        raise HTTPException(415, "Use multipart/form-data with files")
    form = await parse_photos(request)
    try:
        parts = form.getlist("files")
        if (
            not parts
            or len(parts) > MAX_PHOTOS
            or len(parts) != len(form.multi_items())
            or any(not isinstance(part, UploadFile) for part in parts)
        ):
            raise HTTPException(422, "Supply 1 to 10 photographs in files")
        with ExitStack() as stack:
            images = []
            for part in parts:
                if not isinstance(part, UploadFile):
                    raise HTTPException(422, "Invalid photograph")
                image = await run_in_threadpool(
                    stack.enter_context, prepare_image(part)
                )
                images.append(image)
            if user.id is None:
                raise HTTPException(403, "Access forbidden")
            return await run_in_threadpool(
                upload_photos, session, storage, instrument_id, user.id, images
            )

    finally:
        await form.close()


@router.get(
    "", response_model=list[PhotoRead], summary="List active photograph metadata"
)
def list_photos(
    instrument_id: int,
    session: SessionDep,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[PhotoRead]:
    require_instrument(session, instrument_id)
    statement = select(InstrumentPhoto).where(
        InstrumentPhoto.instrument_id == instrument_id,
        InstrumentPhoto.status == "ready",
    )
    response.headers["X-Total-Count"] = str(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    response.headers["Cache-Control"] = "private, no-store"
    return [
        PhotoRead.model_validate(photo)
        for photo in session.exec(
            statement.order_by(
                col(InstrumentPhoto.uploaded_at), col(InstrumentPhoto.id)
            )
            .offset(offset)
            .limit(limit)
        ).all()
    ]


@router.get("/{photo_id}", response_model=PhotoRead, summary="Get photograph metadata")
def metadata(
    instrument_id: int, photo_id: int, session: SessionDep, response: Response
) -> PhotoRead:
    photo = get_photo(session, instrument_id, photo_id)
    response.headers["Cache-Control"] = "private, no-store"
    return PhotoRead.model_validate(photo)


def photo_content(
    instrument_id: int,
    photo_id: int,
    session: SessionDep,
    storage: StorageDep,
    *,
    attachment: bool,
) -> StreamingResponse:
    photo = get_photo(session, instrument_id, photo_id)
    if photo.storage_namespace != storage.namespace:
        raise HTTPException(503, "Photograph storage location unavailable")
    try:
        body = storage.download(photo.storage_key)
        try:
            first = body.read(min(65536, photo.file_size_bytes))
            if not first:
                raise StorageError
        except Exception:
            body.close()
            raise
    except ObjectMissing:
        raise HTTPException(404, "Photograph content unavailable") from None
    except StorageError, OSError:
        raise HTTPException(503, "Photograph content unavailable") from None

    def chunks() -> Iterator[bytes]:
        try:
            yield first
            remaining = photo.file_size_bytes - len(first)
            while remaining > 0:
                chunk = body.read(min(65536, remaining))
                if not chunk:
                    raise StorageError("Incomplete photograph stream")
                remaining -= len(chunk)
                yield chunk
        finally:
            body.close()

    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
        photo.content_type
    ]
    # The original suffix is untrusted and may disagree with the verified format.
    filename = photo.original_filename.rsplit(".", 1)[0] or "photograph"
    filename = f"{filename}.{extension}"
    return StreamingResponse(
        chunks(),
        media_type=photo.content_type,
        headers={
            "Content-Disposition": f"{'attachment' if attachment else 'inline'}; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Length": str(photo.file_size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
        background=BackgroundTask(body.close),
    )


@router.get(
    "/{photo_id}/content",
    response_class=StreamingResponse,
    summary="View a private photograph inline",
)
def view(
    instrument_id: int, photo_id: int, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    return photo_content(instrument_id, photo_id, session, storage, attachment=False)


@router.get(
    "/{photo_id}/download",
    response_class=StreamingResponse,
    summary="Download a private photograph",
)
def download(
    instrument_id: int, photo_id: int, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    return photo_content(instrument_id, photo_id, session, storage, attachment=True)


@router.delete(
    "/{photo_id}",
    response_model=PhotoRead,
    summary="Request recoverable deletion as administrator",
)
def delete_photo(
    instrument_id: int, photo_id: int, user: CurrentUser, session: SessionDep
) -> PhotoRead:
    """Hide a photo without deleting evidence; repeat requests are idempotent."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator required")
    photo = get_photo(session, instrument_id, photo_id, include_deleted=True, lock=True)
    if photo.status == "purging":
        raise HTTPException(409, "Photograph is being permanently deleted")
    if photo.status != "deleted":
        photo.status = "deleted"
        photo.deletion_requested_at = datetime.now(UTC)
        photo.deletion_requested_by_user_id = user.id
        session.add(photo)
        try:
            record_event(
                session,
                AuditAction.PHOTO_DELETION_REQUESTED,
                AuditResource.INSTRUMENT_PHOTO,
                photo.id,
                actor_id=user.id,
                details=AuditDetails(instrument_id=instrument_id),
            )
            result = PhotoRead.model_validate(photo)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            raise HTTPException(503, "Photo metadata unavailable") from None
        return result
    return PhotoRead.model_validate(photo)


@router.post(
    "/{photo_id}/restore",
    response_model=PhotoRead,
    summary="Restore a photo within its recovery period as administrator",
    responses={409: {"description": "Photo cannot be restored"}},
)
def restore(
    instrument_id: int,
    photo_id: int,
    user: PhotoAdmin,
    session: SessionDep,
    storage: StorageDep,
    config: SecuritySettings,
) -> PhotoRead:
    actor_id = user.id
    return restore_photo(session, storage, config, instrument_id, photo_id, actor_id)


@router.get(
    "/{photo_id}/retention",
    response_model=PhotoRetentionRead,
    summary="Inspect retention safeguards as administrator",
)
def read_retention(
    instrument_id: int,
    photo_id: int,
    user: PhotoAdmin,
    session: SessionDep,
    response: Response,
) -> PhotoRetentionRead:
    response.headers["Cache-Control"] = "private, no-store"
    return PhotoRetentionRead.model_validate(
        get_photo(session, instrument_id, photo_id, include_deleted=True)
    )


@router.post(
    "/{photo_id}/retention-hold",
    response_model=PhotoRetentionRead,
    summary="Protect a photo against permanent deletion as administrator",
)
def create_hold(
    instrument_id: int,
    photo_id: int,
    data: RetentionHoldCreate,
    user: PhotoAdmin,
    session: SessionDep,
) -> PhotoRetentionRead:
    return manage_hold(session, instrument_id, photo_id, user.id, data.reason)


@router.delete(
    "/{photo_id}/retention-hold",
    response_model=PhotoRetentionRead,
    summary="Release a photo retention hold as administrator",
)
def release_hold(
    instrument_id: int, photo_id: int, user: PhotoAdmin, session: SessionDep
) -> PhotoRetentionRead:
    return manage_hold(session, instrument_id, photo_id, user.id, None)


@router.post(
    "/{photo_id}/purge-approval",
    response_model=PhotoRetentionRead,
    summary="Approve a deleted photo after reviewing retention requirements",
)
def approve(
    instrument_id: int,
    photo_id: int,
    data: PurgeApproval,
    user: PhotoAdmin,
    session: SessionDep,
) -> PhotoRetentionRead:
    return approve_purge(session, instrument_id, photo_id, user.id)
