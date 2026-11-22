"""Command line: python -m collectors run --source <id>|all."""

import argparse
import sys

import anyio

from collectors.base import SourceId
from collectors.http import Gateway
from collectors.registry import ALL_SOURCES
from collectors.runner import run_all
from common import current_time
from database import DatabaseConfigurationError, get_engine
from observability import configure_logging


class Arguments(argparse.Namespace):
    """Parsed options."""

    source: str = ""


async def collect(sources: list[SourceId]) -> int:
    """Run sources and print one line each; only a failed source makes the command fail."""
    try:
        engine = get_engine()
        try:
            outcomes = await run_all(sources, Gateway(), current_time)
        finally:
            await engine.dispose()
            get_engine.cache_clear()
    except DatabaseConfigurationError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    for outcome in outcomes:
        counts = f"collected={outcome.collected} inserted={outcome.inserted} mapped={outcome.mapped}"
        _ = sys.stdout.write(
            f"{outcome.source} state={outcome.state} {counts} error={outcome.error or '-'}\n",
        )
    return 1 if any(outcome.state == "error" for outcome in outcomes) else 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(prog="python -m collectors")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="collect now")
    _ = run.add_argument("--source", required=True, choices=[*ALL_SOURCES, "all"])
    chosen = parser.parse_args(namespace=Arguments()).source
    configure_logging()
    sources: list[SourceId] = [source for source in ALL_SOURCES if chosen in {source, "all"}]
    return anyio.run(collect, sources)


if __name__ == "__main__":
    sys.exit(main())
