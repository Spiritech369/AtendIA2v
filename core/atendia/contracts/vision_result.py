"""Tenant-configurable image classification result.

The core contract is deliberately semantic-neutral: a tenant owns the
category names through ``PipelineDefinition.vision_doc_mapping`` and the
runner only distinguishes configured document categories from the generic
``product`` and ``unrelated`` buckets.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRODUCT_CATEGORY = "product"
UNRELATED_CATEGORY = "unrelated"
RESERVED_NON_DOCUMENT_CATEGORIES = frozenset({PRODUCT_CATEGORY, UNRELATED_CATEGORY})


class DocumentSide(StrEnum):
    """Optional side hint for two-sided files."""

    FRONT = "front"
    BACK = "back"
    UNKNOWN = "unknown"


class VisionQualityCheck(BaseModel):
    """Structured quality assessment of a submitted image."""

    model_config = ConfigDict(extra="forbid")

    four_corners_visible: bool
    legible: bool
    not_blurry: bool
    no_flash_glare: bool
    not_cut: bool
    side: DocumentSide = DocumentSide.UNKNOWN
    valid_for_file: bool
    rejection_reason: str | None = None


class VisionResult(BaseModel):
    """Classifier output consumed by the runner and trace layer."""

    category: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict
    quality_check: VisionQualityCheck | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> str:
        return str(value).strip().lower()
