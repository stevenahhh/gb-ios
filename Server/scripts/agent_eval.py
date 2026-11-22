"""Measure the assistant's model on natural owner requests through the real loop, without acting.

Every request runs `agent_run.run_agent` in DRY-RUN mode: business handlers are replaced by recorders, the
data is a throwaway copy of the seed inside a schema this script creates and drops, the clock is fixed, and
the only network peer allowed is the model endpoint. The business schema is never read or written.

From Server (the scripted backend needs no key):
    uv run python -m scripts.agent_eval --backend scripted
    uv run python -m scripts.agent_eval --backend live --yes-call-model

DATABASE_URL and DATABASE_SSLMODE name a PostgreSQL whose role may create a schema. The model key is read
from the environment by the model client only; this script checks that it is set and never prints it.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from os import environ
from pathlib import Path
from typing import ClassVar, Final, Literal

import anyio
from pydantic import BaseModel, ConfigDict, JsonValue

from scripts.agent_eval_meter import MODEL_HOST, Meter
from scripts.agent_eval_run import FIXED_NOW, Options, evaluate
from scripts.agent_eval_score import CaseResult, EvalCase, load_cases, load_holdout, summary

SERVER: Final = Path(__file__).resolve().parent.parent
CORPUS: Final = SERVER / "tests" / "agent_corpora" / "eval.json"
KEY_NAME: Final = "CLOVA_STUDIO_API_KEY"
REFUSED: Final = 2
CAPPED: Final = 4
DEFAULT_MAX_CALLS: Final = 400
DEFAULT_MAX_TOKENS: Final = 2_500_000


class Arguments(BaseModel):
    """The command line, parsed into typed values."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    backend: Literal["scripted", "live"]
    yes_call_model: bool
    corpus: Path
    holdout: Path | None
    only: str
    max_calls: int
    max_tokens: int
    out: Path | None


def parse_arguments(argv: Sequence[str] | None) -> Arguments:
    """Read the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ = parser.add_argument("--backend", choices=("scripted", "live"), required=True)
    _ = parser.add_argument("--yes-call-model", action="store_true", help="required for the live backend")
    _ = parser.add_argument("--corpus", type=Path, default=CORPUS, help="plain evaluation file")
    _ = parser.add_argument("--holdout", type=Path, default=None, help="also run the encoded held-out file")
    _ = parser.add_argument("--only", default="", help="comma-separated case ids")
    _ = parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    _ = parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    _ = parser.add_argument("--out", type=Path, default=None, help="also write the JSON to this file")
    return Arguments.model_validate(vars(parser.parse_args(argv)))


def chosen(corpus: Path, holdout: Path | None, only: frozenset[str]) -> tuple[EvalCase, ...]:
    """Read the corpus and, when asked, the held-out cases, keeping the ids named with --only."""
    cases = load_cases(corpus) + (load_holdout(holdout) if holdout is not None else [])
    return tuple(case for case in cases if not only or case.id in only)


def report(
    options: Options, results: Sequence[CaseResult], meter: Meter, prompts: Sequence[int],
) -> dict[str, JsonValue]:
    """Assemble the printed document: cases, totals with intervals, and what the run cost."""
    held = [result for result in results if result.kind == "holdout"]
    document: dict[str, JsonValue] = {
        "meta": {
            "backend": options.backend, "model_host": MODEL_HOST, "now": FIXED_NOW.isoformat(),
            "planned": len(options.cases), "capped": meter.capped, "max_calls": options.max_calls,
            "max_tokens": options.max_tokens, "model_calls": meter.calls, "tokens": meter.tokens,
            "prompt_chars": {
                "calls": len(prompts), "mean": round(sum(prompts) / len(prompts)) if prompts else 0,
                "max": max(prompts, default=0),
            },
        },
        "cases": [
            json.loads(json.dumps(asdict(result), default=str, ensure_ascii=False)) for result in results
        ],
        "totals": summary([result for result in results if result.kind != "holdout"]),
    }
    if held:
        document["holdout"] = summary(held)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    """Check the switches, run the evaluation, and print one JSON document."""
    parsed = parse_arguments(argv)
    live = parsed.backend == "live"
    if live and not parsed.yes_call_model:
        _ = sys.stderr.write("refused: the live backend calls a paid model; pass --yes-call-model\n")
        return REFUSED
    if live and not environ.get(KEY_NAME):
        _ = sys.stderr.write(f"refused: {KEY_NAME} is not set in the environment\n")
        return REFUSED
    if not live and parsed.holdout is not None:
        _ = sys.stderr.write("refused: the held-out file runs only on the live backend\n")
        return REFUSED
    cases = chosen(parsed.corpus, parsed.holdout, frozenset(filter(None, parsed.only.split(","))))
    if not cases:
        _ = sys.stderr.write("refused: no case matches --only\n")
        return REFUSED
    options = Options(
        backend=parsed.backend, cases=cases, max_calls=parsed.max_calls, max_tokens=parsed.max_tokens,
    )
    results: list[CaseResult] = []
    prompts: list[int] = []
    meter = Meter(options.max_calls, options.max_tokens)
    try:
        anyio.run(evaluate, options, results, meter, prompts)
    finally:
        text = json.dumps(report(options, results, meter, prompts), ensure_ascii=False, indent=1)
        _ = sys.stdout.write(text + "\n")
        if parsed.out is not None:
            _ = parsed.out.write_text(text + "\n", encoding="utf-8")
    return CAPPED if meter.capped else 0


if __name__ == "__main__":
    raise SystemExit(main())
