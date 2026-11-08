"""Manage repair defaults under the existing authenticated workshop policy."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func
from sqlmodel import col, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.service import record_event
from atelier_api.database import SessionDep

from .models import RepairTemplate
from .schemas import RepairTemplateCreate, RepairTemplateRead, RepairTemplateUpdate

router = APIRouter(
    prefix="/repair-templates",
    tags=["repair templates"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Workshop access required"},
        503: {"description": "Database unavailable"},
    },
)


@router.post(
    "",
    status_code=201,
    response_model=RepairTemplateRead,
    summary="Create a reusable repair template",
)
def create_template(
    data: RepairTemplateCreate, session: SessionDep, response: Response
) -> RepairTemplateRead:
    template = RepairTemplate(**data.model_dump())
    session.add(template)
    session.flush()
    record_event(
        session,
        AuditAction.REPAIR_TEMPLATE_CREATED,
        AuditResource.REPAIR_TEMPLATE,
        template.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    session.refresh(template)
    response.headers["Cache-Control"] = "private, no-store"
    return RepairTemplateRead.model_validate(template)


@router.get(
    "",
    response_model=list[RepairTemplateRead],
    summary="List repair templates in stable ID order",
)
def list_templates(
    session: SessionDep,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[RepairTemplateRead]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Total-Count"] = str(
        session.exec(select(func.count()).select_from(RepairTemplate)).one()
    )
    rows = session.exec(
        select(RepairTemplate)
        .order_by(col(RepairTemplate.id))
        .offset(offset)
        .limit(limit)
    ).all()
    return [RepairTemplateRead.model_validate(row) for row in rows]


@router.patch(
    "/{template_id}",
    response_model=RepairTemplateRead,
    summary="Change defaults for future repairs only",
    responses={404: {"description": "Repair template not found"}},
)
def update_template(
    template_id: int,
    data: RepairTemplateUpdate,
    session: SessionDep,
    response: Response,
) -> RepairTemplateRead:
    template = session.exec(
        select(RepairTemplate).where(RepairTemplate.id == template_id).with_for_update()
    ).one_or_none()
    if template is None:
        raise HTTPException(404, "Repair template not found")
    changes = {
        name: value
        for name, value in data.model_dump(exclude_unset=True).items()
        if getattr(template, name) != value
    }
    if changes:
        template.sqlmodel_update(changes)
        session.add(template)
        record_event(
            session,
            AuditAction.REPAIR_TEMPLATE_UPDATED,
            AuditResource.REPAIR_TEMPLATE,
            template.id,
            actor_id=session.info.get("audit_actor_id"),
        )
        session.commit()
        session.refresh(template)
    response.headers["Cache-Control"] = "private, no-store"
    return RepairTemplateRead.model_validate(template)
