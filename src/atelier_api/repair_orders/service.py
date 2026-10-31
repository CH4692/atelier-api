"""Compose repair history in batches without loading document contents."""

from sqlalchemy import select
from sqlmodel import Session, col

from .models import RepairDocument, RepairOrder
from .schemas import RepairDocumentRead, RepairOrderDetail, RepairOrderRead


def repair_details(
    session: Session, orders: list[RepairOrder]
) -> list[RepairOrderDetail]:
    """Read metadata for a page of repairs in one query, avoiding binary/N+1 loads."""
    if not orders:
        return []
    ids = [order.id for order in orders]
    rows = (
        session.execute(
            select(
                col(RepairDocument.id),
                col(RepairDocument.repair_order_id),
                col(RepairDocument.filename),
                col(RepairDocument.size_bytes),
                col(RepairDocument.sha256),
                col(RepairDocument.created_at),
            )
            .where(col(RepairDocument.repair_order_id).in_(ids))
            .order_by(col(RepairDocument.created_at), col(RepairDocument.id))
        )
        .mappings()
        .all()
    )
    documents: dict[int, list[RepairDocumentRead]] = {}
    for row in rows:
        metadata = RepairDocumentRead.model_validate(row)
        documents.setdefault(metadata.repair_order_id, []).append(metadata)
    details = []
    for order in orders:
        assert order.id is not None
        details.append(
            RepairOrderDetail(
                **RepairOrderRead.model_validate(order).model_dump(),
                documents=documents.get(order.id, []),
            )
        )
    return details
