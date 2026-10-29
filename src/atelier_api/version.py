"""Read the software version from installed package metadata."""

from importlib.metadata import version


def software_version() -> str:
    """Return the canonical version stamped into the installed distribution."""
    return version("atelier-api")
