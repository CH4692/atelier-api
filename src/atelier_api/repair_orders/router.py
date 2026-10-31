"""Expose dated repair history and authenticated, bounded document access."""

from hashlib import sha256
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlmodel import col, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.service import record_event
from atelier_api.database import SessionDep
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentRead

from .models import MAX_DOCUMENT_BYTES, RepairDocument, RepairOrder
from .schemas import (
    ArchiveUpdate,
    InstrumentHistoryRead,
    RepairDocumentRead,
    RepairOrderCreate,
    RepairOrderDetail,
    RepairOrderRead,
)
from .service import repair_details

router = APIRouter(
    tags=["repairs"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Workshop access required"},
        503: {"description": "Database unavailable"},
    },
)


@router.post(
    "/instruments/{instrument_id}/repair-orders",
    response_model=RepairOrderRead,
    status_code=201,
    summary="Record repair work for an instrument",
    responses={404: {"description": "Instrument not found"}},
)
def create_repair_order(
    instrument_id: int, data: RepairOrderCreate, session: SessionDep
) -> RepairOrderRead:
    instrument = session.exec(
        select(Instrument).where(Instrument.id == instrument_id).with_for_update()
    ).first()
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    order = RepairOrder(
        instrument_id=instrument_id,
        work_description=data.work_description,
        performed_at=data.performed_at,
    )
    session.add(order)
    session.flush()
    record_event(
        session,
        AuditAction.REPAIR_ORDER_CREATED,
        AuditResource.REPAIR_ORDER,
        order.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    session.refresh(order)
    return RepairOrderRead.model_validate(order)


@router.get(
    "/instruments/{instrument_id}/history",
    response_model=InstrumentHistoryRead,
    summary="Get chronological workshop history, including archived repairs",
    responses={
        404: {"description": "Instrument not found"},
        200: {
            "headers": {
                "X-Total-Count": {
                    "description": "Repair count including archived orders, before pagination",
                    "schema": {"type": "integer", "minimum": 0},
                }
            }
        },
    },
)
def get_instrument_history(
    instrument_id: int,
    session: SessionDep,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> InstrumentHistoryRead:
    """Order by work timestamp then ID; include document metadata without blobs.

    Archiving a repair or customer does not hide history. Counts and page queries
    may observe concurrent commits. Page through the history using offset/limit.
    """
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    statement = select(RepairOrder).where(RepairOrder.instrument_id == instrument_id)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Total-Count"] = str(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    orders = session.exec(
        statement.order_by(col(RepairOrder.performed_at), col(RepairOrder.id))
        .offset(offset)
        .limit(limit)
    ).all()
    return InstrumentHistoryRead(
        instrument=InstrumentRead.model_validate(instrument),
        repair_orders=repair_details(session, list(orders)),
    )


@router.get(
    "/repair-orders/{order_id}",
    response_model=RepairOrderDetail,
    summary="Read repair work and document metadata",
    responses={404: {"description": "Repair order not found"}},
)
def get_repair_order(
    order_id: int, session: SessionDep, response: Response
) -> RepairOrderDetail:
    order = session.get(RepairOrder, order_id)
    if order is None:
        raise HTTPException(404, "Repair order not found")
    response.headers["Cache-Control"] = "private, no-store"
    return repair_details(session, [order])[0]


@router.patch(
    "/repair-orders/{order_id}/archive",
    response_model=RepairOrderRead,
    summary="Archive or restore a repair without deleting history",
    responses={404: {"description": "Repair order not found"}},
)
def archive_repair_order(
    order_id: int, data: ArchiveUpdate, session: SessionDep
) -> RepairOrderRead:
    order = session.exec(
        select(RepairOrder).where(RepairOrder.id == order_id).with_for_update()
    ).first()
    if order is None:
        raise HTTPException(404, "Repair order not found")
    if order.is_archived != data.is_archived:
        order.is_archived = data.is_archived
        session.add(order)
        action = (
            AuditAction.REPAIR_ORDER_ARCHIVED
            if data.is_archived
            else AuditAction.REPAIR_ORDER_RESTORED
        )
        record_event(
            session,
            action,
            AuditResource.REPAIR_ORDER,
            order.id,
            actor_id=session.info.get("audit_actor_id"),
        )
        session.commit()
        session.refresh(order)
    return RepairOrderRead.model_validate(order)


@router.post(
    "/repair-orders/{order_id}/documents",
    response_model=RepairDocumentRead,
    status_code=201,
    summary="Store a repair document (binary body, at most 5 MiB)",
    responses={
        404: {"description": "Repair order not found"},
        413: {"description": "Document exceeds 5 MiB"},
        415: {"description": "Use application/octet-stream for the binary body"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def upload_document(
    order_id: int,
    request: Request,
    session: SessionDep,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> RepairDocumentRead:
    """Bound reads before persistence; never fetch external URLs or execute content."""
    if session.get(RepairOrder, order_id) is None:
        raise HTTPException(404, "Repair order not found")
    content_type = (
        request.headers.get("content-type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if content_type != "application/octet-stream":
        raise HTTPException(415, "Use application/octet-stream for the binary body")
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if name in {"", ".", ".."} or any(
        ord(char) < 32 or ord(char) == 127 for char in name
    ):
        raise HTTPException(422, "Invalid document filename")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "Document exceeds 5 MiB")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Document must not be empty")
    document = RepairDocument(
        repair_order_id=order_id,
        filename=name,
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        content=bytes(data),
    )
    session.add(document)
    session.flush()
    record_event(
        session,
        AuditAction.REPAIR_DOCUMENT_CREATED,
        AuditResource.REPAIR_DOCUMENT,
        document.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    session.refresh(document)
    return RepairDocumentRead.model_validate(document)


@router.get(
    "/repair-documents/{document_id}/content",
    summary="Download a repair document as an attachment",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        404: {"description": "Document not found"},
    },
    response_class=Response,
)
def download_document(document_id: int, session: SessionDep) -> Response:
    document = session.get(RepairDocument, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return Response(
        document.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
