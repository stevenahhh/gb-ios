"""What a proactive rule found: one row, why it needs the owner, and the tool it suggests."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Final, Literal

from pydantic import JsonValue

from agent_settings import TOOL_TIERS
from agent_types import ProposalDraft, TargetRef, Tier, ToolName

type FindingKind = Literal[
    "parcel_unpacked", "invoice_missing", "deposit_due", "class_under_min", "order_unconfirmed",
    "inquiry_undrafted", "quote_waiting",
]

DRAFT_TOOLS: Final = frozenset[ToolName]({"save_reply_draft", "save_content_draft"})
KIND_TOOLS: Final[Mapping[FindingKind, ToolName]] = MappingProxyType({
    "parcel_unpacked": "mark_packed", "invoice_missing": "register_invoice",
    "deposit_due": "confirm_deposit", "class_under_min": "add_event",
    "order_unconfirmed": "confirm_order", "inquiry_undrafted": "save_reply_draft",
    "quote_waiting": "record_quote_outcome",
})
EVIDENCE_NEEDED: Final[Mapping[FindingKind, tuple[str, ...]]] = MappingProxyType({
    "parcel_unpacked": ("포장을 마쳤는지",), "invoice_missing": ("송장번호",),
    "deposit_due": ("입금을 확인했는지",), "class_under_min": (),
    "order_unconfirmed": (), "inquiry_undrafted": (), "quote_waiting": ("기관의 답",),
})


@dataclass(frozen=True, slots=True)
class Finding:
    """One row that needs the owner, found by a rule and nothing else."""

    kind: FindingKind
    target: TargetRef
    title: str
    reason: str
    preview: tuple[tuple[str, str], ...]
    args: dict[str, JsonValue]
    day: date

    @property
    def tool(self) -> ToolName:
        """Name the tool the finding suggests."""
        return KIND_TOOLS[self.kind]

    @property
    def tier(self) -> Tier:
        """Read the suggested tool's tier."""
        return TOOL_TIERS[self.tool]

    @property
    def runs_without_owner(self) -> bool:
        """Tell whether the contract lets the tool run with no owner turn: only drafts may."""
        return self.tool in DRAFT_TOOLS

    @property
    def dedupe_key(self) -> str:
        """Name this target and tool for one Seoul day, so it is raised once a day."""
        return f"{self.tool}:{self.target.kind}:{self.target.id}:{self.day.isoformat()}"

    def draft(self) -> ProposalDraft:
        """Shape the finding as a proposal; its target is what approval acts on."""
        return ProposalDraft(
            tool=self.tool, title=self.title, reason=self.reason, target=self.target, args=self.args,
            preview=self.preview, evidence_needed=EVIDENCE_NEEDED[self.kind], dedupe_key=self.dedupe_key,
        )
