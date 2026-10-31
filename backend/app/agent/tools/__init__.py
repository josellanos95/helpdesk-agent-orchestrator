from app.agent.tools.base import Tool, ToolContext, ToolRegistry
from app.agent.tools.helpdesk import HELPDESK_TOOLS


def default_registry() -> ToolRegistry:
    return ToolRegistry(HELPDESK_TOOLS)


__all__ = ["Tool", "ToolContext", "ToolRegistry", "default_registry"]
