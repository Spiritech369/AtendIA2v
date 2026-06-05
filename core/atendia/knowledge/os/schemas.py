from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

JsonDict = dict[str, Any]

KnowledgeSourceType = Literal["file", "url", "faq", "table", "manual"]
KnowledgeContentType = Literal[
    "faq",
    "policy",
    "credit_policy",
    "pricing",
    "catalog",
    "services",
    "appointment_rules",
    "document_rules",
    "location_hours",
    "inventory_color_policy",
    "general",
]
KnowledgeSourceStatus = Literal[
    "draft",
    "processing",
    "active",
    "error",
    "partially_processed",
    "stale",
    "expired",
]
KnowledgeItemStatus = Literal["draft", "active", "error", "stale", "expired"]


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str
    type: KnowledgeSourceType
    content_type: KnowledgeContentType = "general"
    status: KnowledgeSourceStatus = "draft"
    owner: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    priority: int = 0
    metadata: JsonDict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    source_id: UUID
    title: str
    content: str
    structured_data: JsonDict | None = None
    metadata: JsonDict = Field(default_factory=dict)
    active: bool = True
    status: KnowledgeItemStatus = "active"


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    source_id: UUID
    item_id: UUID
    chunk_text: str
    chunk_index: int
    embedding: list[float] | None = None
    metadata: JsonDict = Field(default_factory=dict)
    status: KnowledgeItemStatus = "active"


class KnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    item_id: UUID
    chunk_id: UUID
    source_name: str
    title: str
    snippet: str
    score: float
    source_type: str
    content_type: str
    metadata: JsonDict = Field(default_factory=dict)


class SourceCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    name: str
    type: str
    content_type: str
    status: str
    priority: int = 0
    metadata: JsonDict = Field(default_factory=dict)


class EvidenceSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    text: str
    score: float
    title: str
    source_name: str
    metadata: JsonDict = Field(default_factory=dict)


class EvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answerable: bool
    confidence: float
    snippets: list[EvidenceSnippet] = Field(default_factory=list)
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    source_cards: list[SourceCard] = Field(default_factory=list)
    conflicts: list[JsonDict] = Field(default_factory=list)
    missing_info: str | None = None
    retrieval_log_id: UUID | None = None


class KnowledgeRecord(BaseModel):
    source: KnowledgeSource
    item: KnowledgeItem
    chunk: KnowledgeChunk
    score: float = 0.0
