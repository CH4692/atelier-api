"""Expose staff-only estimate documents and recorded customer approval."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlmodel import col

from atelier_api.database import SessionDep

from .models import RepairEstimate
from .schemas import (
    EstimateApproval,
    EstimateRead,
    EstimateSummary,
    EstimateTransition,
    EstimateWrite,
)
from .service import (
    approve_estimate,
    create_estimate,
    edit_estimate,
    read_estimate,
    require_repair,
    transition_estimate,
)

router = APIRouter(
    prefix="/repairs/{repair_id}/estimates",
    tags=["estimates"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Workshop access required"},
        404: {"description": "Repair or estimate not found"},
        409: {"description": "Document state or repair prevents this operation"},
        503: {"description": "Database unavailable"},
    },
)


@router.post(
    "",
    response_model=EstimateRead,
    status_code=201,
    summary="Create a separate repair estimate revision",
)
def create(
    repair_id: int, data: EstimateWrite, session: SessionDep, response: Response
) -> EstimateRead:
    response.headers["Cache-Control"] = "private, no-store"
    return create_estimate(session, repair_id, data)


@router.get(
    "",
    response_model=list[EstimateSummary],
    summary="List estimate revisions with their approval facts",
)
def list_estimates(
    repair_id: int,
    session: SessionDep,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EstimateSummary]:
    require_repair(session, repair_id)
    query = select(RepairEstimate).where(
        col(RepairEstimate.repair_order_id) == repair_id
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Total-Count"] = str(
        session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    )
    rows = (
        session.execute(
            query.order_by(col(RepairEstimate.revision)).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )
    return [EstimateSummary.model_validate(row) for row in rows]


@router.get(
    "/{estimate_id}",
    response_model=EstimateRead,
    summary="Read an estimate snapshot and exact totals",
)
def get(
    repair_id: int, estimate_id: int, session: SessionDep, response: Response
) -> EstimateRead:
    require_repair(session, repair_id)
    # Draft replacement takes an exclusive document lock; readers share this lock
    # so the returned header and lines cannot come from different draft versions.
    estimate = session.execute(
        select(RepairEstimate)
        .where(
            col(RepairEstimate.id) == estimate_id,
            col(RepairEstimate.repair_order_id) == repair_id,
        )
        .with_for_update(read=True)
    ).scalar_one_or_none()
    if estimate is None:
        raise HTTPException(404, "Estimate not found")
    response.headers["Cache-Control"] = "private, no-store"
    return read_estimate(session, estimate)


@router.patch(
    "/{estimate_id}",
    response_model=EstimateRead,
    summary="Replace all positions of a draft estimate",
)
def edit(
    repair_id: int,
    estimate_id: int,
    data: EstimateWrite,
    session: SessionDep,
    response: Response,
) -> EstimateRead:
    response.headers["Cache-Control"] = "private, no-store"
    return edit_estimate(session, repair_id, estimate_id, data)


@router.patch(
    "/{estimate_id}/status",
    response_model=EstimateRead,
    summary="Issue, reject or withdraw an estimate",
)
def change_status(
    repair_id: int,
    estimate_id: int,
    data: EstimateTransition,
    session: SessionDep,
    response: Response,
) -> EstimateRead:
    response.headers["Cache-Control"] = "private, no-store"
    return transition_estimate(session, repair_id, estimate_id, data.status)


@router.post(
    "/{estimate_id}/approval",
    response_model=EstimateRead,
    summary="Record customer approval of an issued estimate",
)
def approve(
    repair_id: int,
    estimate_id: int,
    data: EstimateApproval,
    session: SessionDep,
    response: Response,
) -> EstimateRead:
    """Record a staff attestation, not an electronic signature or portal action."""
    response.headers["Cache-Control"] = "private, no-store"
    return approve_estimate(session, repair_id, estimate_id, data)
