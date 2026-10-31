from app.agent.tools.base import Tool, ToolContext, ToolRegistry
from app.agent.tools.helpdesk import HELPDESK_TOOLS
from app.agent.tools.knowledge import KNOWLEDGE_TOOLS
from app.agent.tools.sensitive import SENSITIVE_TOOLS


def default_registry() -> ToolRegistry:
    return ToolRegistry([*HELPDESK_TOOLS, *KNOWLEDGE_TOOLS, *SENSITIVE_TOOLS])


__all__ = ["Tool", "ToolContext", "ToolRegistry", "default_registry"]
