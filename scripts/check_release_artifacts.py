"""Verify distribution versions before Semantic Release publishes a tag."""

import argparse
import tarfile
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def verify_artifacts(directory: Path, expected_version: str) -> None:
    """Require exactly one wheel and sdist whose metadata matches the release."""
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError(
            "Release must contain exactly one wheel and one source archive"
        )
    with ZipFile(wheels[0]) as wheel:
        names = [
            name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(names) != 1:
            raise ValueError("Wheel metadata is ambiguous or missing")
        wheel_metadata = wheel.read(names[0])
    with tarfile.open(sources[0]) as source:
        names = [
            name
            for name in source.getnames()
            if name.count("/") == 1 and name.endswith("/PKG-INFO")
        ]
        if len(names) != 1:
            raise ValueError("Source metadata is ambiguous or missing")
        metadata_file = source.extractfile(names[0])
        if metadata_file is None:
            raise ValueError("Source metadata is not a file")
        source_metadata = metadata_file.read()
    for raw in (wheel_metadata, source_metadata):
        metadata = BytesParser().parsebytes(raw)
        if metadata["Name"] != "atelier-api" or metadata["Version"] != expected_version:
            raise ValueError("Distribution metadata does not match the planned release")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    arguments = parser.parse_args()
    verify_artifacts(Path("dist"), arguments.version)
    print("Wheel and source metadata match the planned release.")


if __name__ == "__main__":
    main()
