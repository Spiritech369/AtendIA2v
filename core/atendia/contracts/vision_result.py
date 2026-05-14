"""Output of OpenAI Vision classifier.

Fase 3c.2 → Fase 3 (motos crédito flow):

Originally Vision returned just `category + confidence + metadata: dict`
and the composer prompt inferred whether to accept the doc. That left
the "accepted vs rejected" decision in LLM-land, which made the
`docs_complete_for_plan` evaluator's status writes unreliable (the
runner had nothing to write because no deterministic decision existed).

This module now also defines `VisionQualityCheck` — a fixed-schema
sub-object the model populates for doc categories. The runner reads
it deterministically to decide:

  - `valid_for_credit_file=true` → write `customer.attrs[DOCS_X] = {status:"ok"}`
  - `valid_for_credit_file=false` → write `{status:"rejected",
                                            rejection_reason: <model text>}`

`quality_check` stays Optional for back-compat: legacy Vision calls
(e.g. a tenant with an older prompt or a moto/unrelated category)
return `None` and the runner falls back to its previous heuristic.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class VisionCategory(str, Enum):
    """Categorías que el classifier puede asignar.

    Las primeras 7 son tipos de doc del v1 prompt; "moto" y
    "unrelated" capturan los casos donde el cliente mandó algo
    fuera del flujo de papelería.
    """

    INE = "ine"
    COMPROBANTE = "comprobante"
    RECIBO_NOMINA = "recibo_nomina"
    ESTADO_CUENTA = "estado_cuenta"
    CONSTANCIA_SAT = "constancia_sat"
    FACTURA = "factura"
    IMSS = "imss"
    MOTO = "moto"
    UNRELATED = "unrelated"


class DocumentSide(str, Enum):
    """Some docs are two-sided (INE). The side field tells the runner
    which canonical attr key to write — DOCS_INE_FRENTE vs
    DOCS_INE_REVERSO when the tenant configured that split. Defaults
    to UNKNOWN, the runner then writes to the generic key when present
    in `pipeline.vision_doc_mapping`.
    """

    FRONT = "front"
    BACK = "back"
    UNKNOWN = "unknown"


class VisionQualityCheck(BaseModel):
    """Structured quality assessment of the submitted image.

    Filled by the classifier when category is a doc class (not moto /
    unrelated). The fields mirror what an operator visually checks
    before approving a doc; the model fills them honestly so the
    runner can reject deterministically (no "looks fine to me" LLM
    judgment).

    `valid_for_credit_file` is the runner's go/no-go signal — true =
    accept, false = reject + use `rejection_reason` in the composer
    reply.
    """

    model_config = ConfigDict(extra="forbid")

    four_corners_visible: bool
    legible: bool
    not_blurry: bool
    no_flash_glare: bool
    not_cut: bool
    side: DocumentSide = DocumentSide.UNKNOWN
    valid_for_credit_file: bool
    rejection_reason: str | None = None


class VisionResult(BaseModel):
    """Resultado del classifier de imágenes.

    `metadata` is the legacy free dict (kept for back-compat with
    existing prompts/snapshots). `quality_check` is the Fase 3
    structured sub-object — populated only for doc-category images;
    `None` for `moto` / `unrelated` / legacy outputs.
    """

    category: VisionCategory
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict
    quality_check: VisionQualityCheck | None = None
