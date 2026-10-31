"""Generate printable labels containing stable links rather than personal data."""

from io import BytesIO
from uuid import UUID

import qrcode
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse, Response
from qrcode.image.svg import SvgPathFillImage
from sqlmodel import select

from atelier_api.auth.dependencies import SecuritySettings
from atelier_api.database import SessionDep
from atelier_api.settings import Settings

from .models import Instrument

router = APIRouter(prefix="/instruments", tags=["instruments"])
scan_router = APIRouter(tags=["instruments"])


def instrument_url(config: Settings, public_id: UUID) -> str:
    """Use only the configured origin; identifiers convey no access authority."""
    if config.public_qr_base_url is None:
        raise HTTPException(503, "PUBLIC_QR_BASE_URL is not configured")
    return f"{config.public_qr_base_url}/i/{public_id}"


def qr_svg(url: str) -> bytes:
    """Render a black-on-white SVG with the required four-module quiet zone."""
    code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathFillImage)
    output = BytesIO()
    image.save(output)
    return output.getvalue()


@router.get(
    "/{instrument_id}/qr-code.svg",
    summary="Download a printable instrument QR code",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}, 404: {}, 503: {}},
)
def get_qr_code(
    instrument_id: int, session: SessionDep, config: SecuritySettings
) -> Response:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    url = instrument_url(config, instrument.public_id)
    return Response(
        qr_svg(url),
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'attachment; filename="instrument-{instrument_id}.svg"',
            "Content-Location": url,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@scan_router.get(
    "/i/{public_id}",
    summary="Resolve a stable instrument link after staff authentication",
    response_class=RedirectResponse,
    status_code=307,
    responses={404: {"description": "Instrument not found"}},
)
def resolve_instrument(public_id: UUID, session: SessionDep) -> RedirectResponse:
    """Keep printed links stable independently of the current record API route."""
    instrument = session.exec(
        select(Instrument).where(Instrument.public_id == public_id)
    ).first()
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    return RedirectResponse(
        f"/api/v1/instruments/{instrument.id}",
        status_code=307,
        headers={"Cache-Control": "private, no-store"},
    )
