"""Canonical conversation-scoped state for Dinamo (Phase 3c.2).

Lives in conversation_state.extracted_data JSONB. NLU writes here,
router and composer read. Hardcoded shape — Dinamo es el único tenant
en 3c.2; cuando se onboarde un segundo vertical, refactorizar a
JSONB-config (decisión #9 del design doc).
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict


class TipoCredito(str, Enum):
    """Cinco tipos de crédito del v1 prompt — uno por respuesta del menú."""

    NOMINA_TARJETA = "Nómina Tarjeta"
    NOMINA_RECIBOS = "Nómina Recibos"
    PENSIONADOS = "Pensionados"
    NEGOCIO_SAT = "Negocio SAT"
    SIN_COMPROBANTES = "Sin Comprobantes"


class PlanCredito(str, Enum):
    """Porcentaje de enganche según el plan asignado."""

    PLAN_10 = "10%"
    PLAN_15 = "15%"
    PLAN_20 = "20%"


class ExtractedFields(BaseModel):
    """Estado conversacional canónico.

    Convención: campos en español respetando el v1 prompt y los
    términos que la NLU ya conoce. Flags de docs siguen el patrón
    `docs_<key>: bool`; el helper next_pending_doc() (T3) los itera.
    """

    model_config = ConfigDict(use_enum_values=False)

    # Personal
    antigüedad_meses: int | None = None
    nombre: str | None = None

    # Plan (asignado en PLAN MODE)
    tipo_credito: TipoCredito | None = None
    plan_credito: PlanCredito | None = None

    # Sales (asignados en SALES MODE)
    modelo_moto: str | None = None
    tipo_moto: str | None = None  # categoría: "Motoneta", "Chopper", etc.

    # Docs (DOC MODE marca true al recibir/validar cada uno)
    docs_ine: bool = False
    docs_comprobante: bool = False
    docs_estados_de_cuenta: bool = False
    docs_nomina: bool = False
    docs_constancia_sat: bool = False
    docs_factura: bool = False
    docs_imss: bool = False
    papeleria_completa: bool = False

    # Conversacionales
    retention_attempt: bool = False
    cita_dia: str | None = None  # ISO date
