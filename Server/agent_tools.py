"""The tool registry: every tool the model may be offered, by name.

T3 actions (sending or sharing to a customer, refunds, payments, deleting, changing a setting, price,
or rule, completing a reply, overriding a lock) are not tools, so no decision can allow them.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from pydantic import JsonValue

from agent_memory import MEMORIES
from agent_tools_cases import CASES
from agent_tools_deals import DEALS
from agent_tools_desk import DESK
from agent_tools_drafts import DRAFTS
from agent_tools_orders import ORDERS
from agent_tools_read import READS
from agent_types import Tool

TOOLS: Final[Mapping[str, Tool]] = MappingProxyType(
    {tool.rule.name: tool for tool in (*READS, *DESK, *DRAFTS, *MEMORIES, *ORDERS, *DEALS, *CASES)},
)


def registry() -> Mapping[str, Tool]:
    """Return every tool the agent knows, by name."""
    return TOOLS


def tool_definitions(tools: Mapping[str, Tool]) -> list[dict[str, JsonValue]]:
    """Describe the tools the way the chat model is told about them."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.rule.name,
                "description": f"{tool.title}: {tool.description}",
                "parameters": tool.parameters,
            },
        }
        for tool in tools.values()
    ]
