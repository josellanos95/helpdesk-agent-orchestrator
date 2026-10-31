"""What an eval run records: what the employee said, what the agent answered and did, and the database
facts left behind. Checks read these records; they never talk to the database or the model."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ToolRecord:
    name: str
    arguments: dict
    result: dict | list | None
    error: str | None = None


@dataclass
class State:
    """Database facts for one simulated employee after a turn."""

    tickets: list[dict] = field(default_factory=list)  # id, subject, priority, category, status
    approvals: list[dict] = field(default_factory=list)  # tool, status
    escalations: list[dict] = field(default_factory=list)  # urgency, status
    audit: list[str] = field(default_factory=list)  # actions recorded about this employee


@dataclass
class Turn:
    user: str
    reply: str
    status: str  # completed | failed | max_steps | error
    tools: list[ToolRecord]
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    seconds: float  # wall clock for the whole turn
    llm_seconds: float  # time spent inside the model calls
    state: State
    error: str | None = None


@dataclass
class Transcript:
    case_id: str
    model: str
    turns: list[Turn]

    @property
    def final(self) -> State:
        return self.turns[-1].state if self.turns else State()

    @property
    def tool_names(self) -> list[str]:
        return [t.name for turn in self.turns for t in turn.tools]

    @property
    def replies(self) -> list[str]:
        return [turn.reply for turn in self.turns]
