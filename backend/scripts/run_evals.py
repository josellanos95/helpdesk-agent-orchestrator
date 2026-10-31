"""Run the agent behaviour evals against a real model. Costs money: read the numbers it prints first.

    python -m scripts.run_evals --list
    python -m scripts.run_evals --model gpt-5-nano --repeat 1 --max-usd 0.10
    python -m scripts.run_evals --model gpt-5-mini --repeat 3 --max-usd 1.00 --case kb_ --case ticket_
    python -m scripts.run_evals --compare evals/results/a.json evals/results/b.json
    python -m scripts.run_evals --cleanup            # remove throwaway tenants left by a killed run

It builds throwaway copies of the demo companies, plays every case with a fresh employee and deletes them
afterwards (see evals/harness.py). Needs Postgres up and OPENAI_API_KEY in backend/.env. `--offline` uses
the free hashing embedder (retrieval is then NOT representative) and still needs a model.
"""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

from app.agent import prompts
from app.config import get_settings
from app.llm.embeddings import HashingEmbedder, build_embedder
from app.llm.openai_client import OpenAIClient
from app.llm.pricing import is_priced
from evals import report
from evals.cases import CASES
from evals.harness import Budget, Outcome, delete_stale_tenants, run_suite

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results"


def _progress(outcome: Outcome) -> None:
    mark = "skip" if outcome.skipped else "ok  " if outcome.passed else "FAIL"
    detail = "" if outcome.passed or outcome.skipped else f"  <- {outcome.failures[0][0]}"
    print(f"  {mark} {outcome.case_id} #{outcome.repeat + 1}{detail}", flush=True)


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set (put it in backend/.env).")
    model = args.model or settings.openai_model
    effort = args.reasoning_effort or settings.openai_reasoning_effort
    label = args.label or (f"{model}@{effort}" if effort else model)
    if args.prompt_file:  # try another system prompt without editing the code
        prompts.SYSTEM_PROMPT = Path(args.prompt_file).read_text(encoding="utf-8")
    if not is_priced(model):
        raise SystemExit(f"{model} is not in the price table (app/llm/pricing.py): costs would read as $0.")

    chosen = [c for c in CASES if not args.case or any(c.id.startswith(p) or p in c.id for p in args.case)]
    if not chosen:
        raise SystemExit("No case matches --case.")
    embedder = HashingEmbedder() if args.offline else build_embedder(settings)
    if embedder is None:
        raise SystemExit("No embedding provider: set OPENAI_API_KEY, or pass --offline.")

    runs = len(chosen) * args.repeat
    print(f"{runs} runs ({len(chosen)} cases x {args.repeat}), model {label}, cap ${args.max_usd}, "
          f"concurrency {args.concurrency}", flush=True)  # fmt: skip
    llm = OpenAIClient(api_key=settings.openai_api_key, model=model, reasoning_effort=effort)
    budget = Budget(Decimal(str(args.max_usd)))
    outcomes, _ = await run_suite(
        llm=llm,
        embedder=embedder,
        cases=chosen,
        repeat=args.repeat,
        concurrency=args.concurrency,
        budget=budget,
        max_steps=settings.agent_max_steps,
        on_done=_progress,
    )
    summary = report.summarize(label, outcomes)
    print("\n" + report.format_summary(summary))
    path = report.save(RESULTS, label, args.repeat, budget.spent, outcomes)
    print(f"\nspent ${budget.spent:.4f} (cap ${args.max_usd}); full transcripts in {path}")


def compare(paths: list[str]) -> None:
    summaries = [json.loads(Path(p).read_text(encoding="utf-8"))["summary"] for p in paths]
    print(report.comparison_table(summaries))


def regrade(paths: list[str], details: bool) -> None:
    """Grade saved runs again with the current checks (free: no model calls) and compare them."""
    summaries = []
    for path in paths:
        label, outcomes = report.load(Path(path))
        summaries.append(report.summarize(label, outcomes))
        if details:
            print(report.format_summary(summaries[-1]) + "\n")
    print(report.comparison_table(summaries))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # replies can hold characters a Windows console cannot print
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"])
    parser.add_argument("--prompt-file", help="a text file to use as the system prompt template")
    parser.add_argument("--label", help="name for this arm in the report (default: model[@effort])")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-usd", type=float, default=0.25)
    parser.add_argument("--case", action="append", help="run only cases whose id contains this (repeatable)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--compare", nargs="+", metavar="RESULT_JSON")
    parser.add_argument("--regrade", nargs="+", metavar="RESULT_JSON", help="grade saved runs again, free")
    parser.add_argument("--details", action="store_true", help="with --regrade: print each run's failures")
    args = parser.parse_args()

    if args.list:
        for case in CASES:
            print(f"{case.area:11} {case.id:42} {len(case.turns)} turn(s), {len(case.checks)} checks")
        sys.exit(0)
    if args.compare:
        compare(args.compare)
        sys.exit(0)
    if args.regrade:
        regrade(args.regrade, args.details)
        sys.exit(0)
    if args.cleanup:
        print(f"removed {asyncio.run(delete_stale_tenants())} throwaway tenant(s)")
        sys.exit(0)
    asyncio.run(main(args))
