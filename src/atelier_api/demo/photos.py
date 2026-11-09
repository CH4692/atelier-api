"""Publish clearly labelled synthetic demo illustrations through existing storage."""

from io import BytesIO

from PIL import Image, ImageDraw
from sqlmodel import Session, select
from starlette.datastructures import UploadFile

from atelier_api.instruments.models import Instrument
from atelier_api.photos.images import prepare_image
from atelier_api.photos.models import InstrumentPhoto
from atelier_api.photos.service import remove_pending, upload_photos
from atelier_api.photos.storage import StorageService
from atelier_api.settings import Settings
from atelier_api.users.models import User

from .data import PREFIX, PROFILE
from .service import guard_target


def illustration(index: int, view: int) -> bytes:
    """Create an original schematic, never a purported photograph of a real object."""
    with Image.new("RGB", (320, 480), "#f6efdf") as image:
        draw = ImageDraw.Draw(image)
        draw.text((20, 18), "FIKTIVE DEMO-ILLUSTRATION", fill="#493524")
        draw.text((20, 40), f"Klanggarten / Instrument {index + 1:03}", fill="#493524")
        color = (145 + index % 35, 79 + index % 20, 37)
        draw.ellipse((85, 135, 235, 270), fill=color, outline="#493524", width=3)
        draw.ellipse((70, 235, 250, 410), fill=color, outline="#493524", width=3)
        draw.rectangle((145, 78, 175, 255), fill="#493524")
        draw.line((160, 80, 160, 365), fill="#ddd2bb", width=3)
        draw.line((130, 315, 190, 315), fill="#efcf90", width=5)
        draw.text(
            (20, 440),
            "Uebersicht" if view == 0 else "Detail: Steg und Decke",
            fill="#493524",
        )
        if view:
            draw.ellipse((115, 285, 205, 345), outline="#af3928", width=4)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def seed_photos(session: Session, config: Settings, storage: StorageService) -> int:
    """Resume 50 real uploads without creating metadata for nonexistent binaries.

    Run after the database phase commits, under the CLI's session advisory lock.
    Native upload intents and compensation remain durable across failures.
    """
    guard_target(config)
    guard_target(config, session.get_bind().engine.url)
    marker = session.exec(
        select(Instrument).where(Instrument.identification_number == f"{PREFIX}0001")
    ).one_or_none()
    if marker is None or not (marker.notes or "").startswith(PROFILE + ";as_of="):
        raise ValueError(
            "Seed the complete small database profile before uploading photos."
        )
    actor = session.exec(
        select(User).where(User.email == "meister.demo@example.com")
    ).one()
    assert actor.id is not None
    for index in range(25):
        instrument = session.exec(
            select(Instrument).where(
                Instrument.identification_number == f"{PREFIX}{index + 1:04}"
            )
        ).one()
        assert instrument.id is not None
        for view in range(2):
            filename = f"{PROFILE}-{index + 1:03}-{view}.png"
            rows = session.exec(
                select(InstrumentPhoto).where(
                    InstrumentPhoto.instrument_id == instrument.id,
                    InstrumentPhoto.original_filename == filename,
                )
            ).all()
            if len(rows) > 1:
                raise ValueError(
                    "Duplicate demo photo records require manual inspection."
                )
            if rows:
                photo = rows[0]
                if photo.storage_namespace != storage.namespace:
                    raise ValueError("Demo photos belong to another storage namespace.")
                if photo.status == "ready":
                    if not storage.exists(photo.storage_key):
                        raise ValueError(
                            "A demo photo binary is missing; metadata will not be fabricated or overwritten."
                        )
                    continue
                if photo.status != "pending":
                    raise ValueError(
                        "Deleted or retained photo evidence will not be automatically restored."
                    )
                assert photo.id is not None
                remove_pending(session, storage, ids=[photo.id])
                if session.get(InstrumentPhoto, photo.id) is not None:
                    raise ValueError(
                        "Pending photo cleanup failed; retry storage recovery first."
                    )
            with (
                BytesIO(illustration(index, view)) as source,
                prepare_image(UploadFile(source, filename=filename)) as image,
            ):
                upload_photos(session, storage, instrument.id, actor.id, [image])
    return 50
