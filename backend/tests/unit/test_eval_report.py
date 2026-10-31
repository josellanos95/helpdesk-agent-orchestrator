"""Saving a run and grading it again later must give the same verdicts: that is what makes fixing a wrong
check free."""

from decimal import Decimal

from evals import report
from evals.cases import CASES
from evals.harness import Outcome, grade
from evals.transcript import State, ToolRecord, Transcript, Turn

PASSWORD_CASE = next(c for c in CASES if c.id == "password_reset_waits_for_approval")


def transcript(reply: str, *, approved: bool) -> Transcript:
    state = State(approvals=[{"tool": "reset_password", "status": "pending"}] if approved else [])
    tools = (
        [ToolRecord("reset_password", {"reason": "forgot"}, {"status": "pending_approval"})]
        if approved
        else []
    )
    turn = Turn("reset it", reply, "completed", tools, 2, 300, 40, Decimal("0.002"), 4.5, 3.9, state)
    return Transcript(PASSWORD_CASE.id, "test-model", [turn])


def test_a_saved_run_loads_back_and_grades_the_same(tmp_path):
    outcomes = [
        Outcome(PASSWORD_CASE.id, 0, good := transcript("It is waiting for approval.", approved=True), []),
        Outcome(
            PASSWORD_CASE.id, 1, bad := transcript("Done, I've reset your password.", approved=False), []
        ),
    ]
    for outcome in outcomes:
        outcome.failures = grade(PASSWORD_CASE, outcome.transcript)
    assert outcomes[0].passed and not outcomes[1].passed

    path = report.save(tmp_path, "test model@low", 2, Decimal("0.004"), outcomes)
    assert path.name.endswith("test_model@low.json")  # a label with spaces is safe as a filename

    label, loaded = report.load(path)
    assert label == "test model@low"
    assert [o.passed for o in loaded] == [True, False]
    assert [name for name, _ in loaded[1].failures] == [name for name, _ in outcomes[1].failures]
    assert good.turns[0].reply == loaded[0].transcript.turns[0].reply
    assert bad.turns[0].cost_usd == loaded[1].transcript.turns[0].cost_usd


def test_summary_counts_runs_stability_and_cost():
    ok = Outcome(PASSWORD_CASE.id, 0, transcript("It is waiting for approval.", approved=True), [])
    ok.failures = grade(PASSWORD_CASE, ok.transcript)
    ko = Outcome(PASSWORD_CASE.id, 1, transcript("Done, I've reset your password.", approved=False), [])
    ko.failures = grade(PASSWORD_CASE, ko.transcript)
    skipped = Outcome(PASSWORD_CASE.id, 2, None, [("budget", "cap")], skipped=True)

    summary = report.summarize("m", [ok, ko, skipped])
    assert (summary["runs"], summary["passed"], summary["skipped"]) == (2, 1, 1)
    assert summary["stable_cases"] == 0
    assert summary["areas"]["approvals"] == {"passed": 1, "runs": 2}
    assert summary["cost_per_turn_usd"] == 0.002
    assert "1/2 runs passed" in report.format_summary(summary)
    assert "m" in report.comparison_table([summary])
