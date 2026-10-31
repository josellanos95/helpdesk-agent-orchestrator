"""Turns eval outcomes into numbers: pass rates, latency, tokens, cost; and a side-by-side table."""

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from evals.cases import CASES
from evals.harness import Outcome, grade
from evals.transcript import State, ToolRecord, Transcript, Turn

AREA_OF = {case.id: case.area for case in CASES}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(model: str, outcomes: list[Outcome]) -> dict:
    played = [o for o in outcomes if not o.skipped]
    turns = [t for o in played for t in o.transcript.turns]
    by_case: dict[str, list[Outcome]] = defaultdict(list)
    for o in played:
        by_case[o.case_id].append(o)

    cases = {}
    for case_id, runs in by_case.items():
        failing = Counter(name for o in runs for name, _ in o.failures)
        example = {}
        for o in runs:
            for name, detail in o.failures:
                example.setdefault(name, detail)
        cases[case_id] = {
            "area": AREA_OF.get(case_id, "?"),
            "passed": sum(o.passed for o in runs),
            "runs": len(runs),
            "failing_checks": dict(failing),
            "example": example,
        }

    areas: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in cases.values():
        areas[row["area"]][0] += row["passed"]
        areas[row["area"]][1] += row["runs"]

    cost = sum((t.cost_usd for t in turns), Decimal(0))
    seconds = [t.seconds for t in turns]
    return {
        "model": model,
        "runs": len(played),
        "skipped": len(outcomes) - len(played),
        "passed": sum(o.passed for o in played),
        "stable_cases": sum(r["passed"] == r["runs"] for r in cases.values()),
        "cases": len(cases),
        "areas": {name: {"passed": p, "runs": n} for name, (p, n) in sorted(areas.items())},
        "turns": len(turns),
        "latency_p50_s": round(_percentile(seconds, 0.5), 1),
        "latency_p95_s": round(_percentile(seconds, 0.95), 1),
        "llm_calls_per_turn": round(sum(t.llm_calls for t in turns) / max(1, len(turns)), 2),
        "tokens_in_per_turn": round(sum(t.prompt_tokens for t in turns) / max(1, len(turns))),
        "tokens_out_per_turn": round(sum(t.completion_tokens for t in turns) / max(1, len(turns))),
        "cost_total_usd": float(cost),
        "cost_per_turn_usd": float(cost / max(1, len(turns))),
        "infrastructure_errors": sum(1 for t in turns if t.status in {"failed", "error"}),
        "per_case": cases,
    }


def runs_as_json(outcomes: list[Outcome]) -> list[dict]:
    rows = []
    for o in outcomes:
        row = {
            "case": o.case_id,
            "repeat": o.repeat,
            "passed": o.passed,
            "skipped": o.skipped,
            "failures": o.failures,
        }
        if o.transcript:
            row["turns"] = [
                {
                    "user": t.user,
                    "reply": t.reply,
                    "status": t.status,
                    "tools": [{"name": x.name, "arguments": x.arguments, "error": x.error} for x in t.tools],
                    "llm_calls": t.llm_calls,
                    "tokens": [t.prompt_tokens, t.completion_tokens],
                    "cost_usd": float(t.cost_usd),
                    "seconds": round(t.seconds, 2),
                    "llm_seconds": round(t.llm_seconds, 2),
                    "state": asdict(t.state),
                    "error": t.error,
                }
                for t in o.transcript.turns
            ]
        rows.append(row)
    return rows


def save(directory: Path, model: str, repeat: int, spent: Decimal, outcomes: list[Outcome]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w.@-]+", "_", model)
    path = directory / f"{stamp}-{safe}.json"
    payload = {
        "model": model,
        "created": stamp,
        "repeat": repeat,
        "spent_usd": float(spent),
        "summary": summarize(model, outcomes),
        "runs": runs_as_json(outcomes),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: Path) -> tuple[str, list[Outcome]]:
    """Rebuild the outcomes of a saved run and grade them again with today's checks.

    Free: it reads the transcript, it does not call the model. This is how a check that turned out to be
    wrong is fixed without paying for the run again. Tool *results* are not saved, so checks that need them
    cannot be regraded (none do).
    """
    saved = json.loads(path.read_text(encoding="utf-8"))
    cases = {case.id: case for case in CASES}
    outcomes = []
    for row in saved["runs"]:
        case = cases.get(row["case"])
        if case is None:  # the case was removed or renamed since
            continue
        if row["skipped"] or "turns" not in row:
            outcomes.append(Outcome(row["case"], row["repeat"], None, row["failures"], skipped=True))
            continue
        turns = [
            Turn(
                user=t["user"],
                reply=t["reply"],
                status=t["status"],
                tools=[ToolRecord(x["name"], x["arguments"], None, x["error"]) for x in t["tools"]],
                llm_calls=t["llm_calls"],
                prompt_tokens=t["tokens"][0],
                completion_tokens=t["tokens"][1],
                cost_usd=Decimal(str(t["cost_usd"])),
                seconds=t["seconds"],
                llm_seconds=t.get("llm_seconds", 0.0),
                state=State(**t["state"]),
                error=t["error"],
            )
            for t in row["turns"]
        ]
        transcript = Transcript(row["case"], saved["model"], turns)
        outcomes.append(Outcome(row["case"], row["repeat"], transcript, grade(case, transcript)))
    return saved["model"], outcomes


def format_summary(summary: dict) -> str:
    lines = [
        f"model {summary['model']}: {summary['passed']}/{summary['runs']} runs passed, "
        f"{summary['stable_cases']}/{summary['cases']} cases passed every time",
        f"latency per turn p50 {summary['latency_p50_s']}s p95 {summary['latency_p95_s']}s, "
        f"{summary['llm_calls_per_turn']} model calls, {summary['tokens_in_per_turn']} in / "
        f"{summary['tokens_out_per_turn']} out tokens, ${summary['cost_per_turn_usd']:.4f} per turn "
        f"(${summary['cost_total_usd']:.3f} total)",
        "by area: " + ", ".join(f"{a} {v['passed']}/{v['runs']}" for a, v in summary["areas"].items()),
    ]
    if summary["skipped"]:
        lines.append(f"{summary['skipped']} run(s) skipped: spend cap reached")
    if summary["infrastructure_errors"]:
        lines.append(f"{summary['infrastructure_errors']} turn(s) failed on the model/API side")
    for case_id, row in summary["per_case"].items():
        if row["passed"] == row["runs"]:
            continue
        lines.append(f"\n  {case_id}  {row['passed']}/{row['runs']}")
        for name, times in row["failing_checks"].items():
            lines.append(f"    x {name} ({times}x): {row['example'][name][:200]}")
    return "\n".join(lines)


def comparison_table(summaries: list[dict]) -> str:
    """Markdown table, one column per model."""
    head = "| | " + " | ".join(s["model"] for s in summaries) + " |"
    sep = "|---|" + "---|" * len(summaries)

    def row(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(fn(s) for s in summaries) + " |"

    rows = [
        head,
        sep,
        row("Runs passed", lambda s: f"{s['passed']}/{s['runs']} ({s['passed'] / max(1, s['runs']):.0%})"),
        row("Cases that passed every time", lambda s: f"{s['stable_cases']}/{s['cases']}"),
        row("Latency per turn, median", lambda s: f"{s['latency_p50_s']} s"),
        row("Latency per turn, p95", lambda s: f"{s['latency_p95_s']} s"),
        row("Model calls per turn", lambda s: str(s["llm_calls_per_turn"])),
        row(
            "Tokens per turn (in / out)", lambda s: f"{s['tokens_in_per_turn']} / {s['tokens_out_per_turn']}"
        ),
        row("Cost per turn", lambda s: f"${s['cost_per_turn_usd']:.4f}"),
    ]
    areas = sorted({a for s in summaries for a in s["areas"]})
    for area in areas:
        rows.append(
            row(
                f"· {area}",
                lambda s, a=area: (
                    f"{s['areas'][a]['passed']}/{s['areas'][a]['runs']}" if a in s["areas"] else "-"
                ),
            )
        )
    return "\n".join(rows)
