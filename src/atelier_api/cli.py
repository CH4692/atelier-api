"""Start the API through the installed command-line entry point."""

import argparse

import uvicorn


def main() -> None:
    """Parse server options and run Uvicorn without development auto-reload."""
    parser = argparse.ArgumentParser(description="Run the Atelier API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("atelier_api.main:app", host=args.host, port=args.port)
