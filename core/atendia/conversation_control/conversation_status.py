from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


ConversationStatus = Literal["OPEN_BOT", "OPEN_HUMAN", "BOT_PAUSED", "ESCALATED", "CLOSED"]
OwnerType = Literal["bot", "human", "team", "none"]


class ConversationControlResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_allowed: bool
    conversation_status: ConversationStatus
    owner_type: OwnerType
    owner_id: str | None = None
    pause_reason: str | None = None
    handoff_required: bool = False

    @model_validator(mode="after")
    def _human_or_paused_blocks_bot(self) -> "ConversationControlResult":
        if self.conversation_status in {"OPEN_HUMAN", "BOT_PAUSED", "ESCALATED", "CLOSED"}:
            if self.bot_allowed:
                raise ValueError(f"{self.conversation_status} requires bot_allowed=false")
        if self.owner_type in {"human", "team"} and self.bot_allowed:
            raise ValueError("human/team owner requires bot_allowed=false")
        return self


__all__ = ["ConversationControlResult", "ConversationStatus", "OwnerType"]
