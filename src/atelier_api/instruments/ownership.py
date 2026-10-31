"""Resolve partial ownership updates and attribute database-generated history."""

from sqlalchemy import text
from sqlmodel import Session

from .models import Instrument
from .schemas import InstrumentOwnership, InstrumentUpdate


def set_ownership_actor(session: Session) -> None:
    """Set transaction-local attribution using only authenticated adapter output."""
    actor = session.info.get("audit_actor_id")
    session.execute(
        text("SELECT set_config('atelier.ownership_actor_id', :actor, true)"),
        {"actor": str(actor) if isinstance(actor, int) else ""},
    )


def ownership_changes(instrument: Instrument, update: InstrumentUpdate) -> dict:
    """Validate the merged state without implicitly dropping an existing owner.

    Legacy customer-only updates retain their previous assignment semantics.
    Explicit category updates must explicitly clear an incompatible customer ID.
    """
    changes = update.model_dump(exclude_unset=True)
    if "customer_id" in changes and "ownership" not in changes:
        category = instrument.ownership
        if changes["customer_id"] is not None:
            category = InstrumentOwnership.CUSTOMER
        elif category == InstrumentOwnership.CUSTOMER:
            category = InstrumentOwnership.UNASSIGNED
        changes["ownership"] = category
    category = changes.get("ownership", instrument.ownership)
    customer_id = changes.get("customer_id", instrument.customer_id)
    if customer_id is not None and category != InstrumentOwnership.CUSTOMER:
        raise ValueError(
            "Clear customer_id explicitly when changing to workshop or unassigned ownership"
        )
    return changes
