"""Output of OpenAI Vision classifier (Phase 3c.2).

Clasificación absoluta — el clasificador no recibe contexto de qué
doc esperabamos (sin confirmation bias). El runner compara
result.category contra next_pending_doc() para decidir el flujo.
"""
from enum import Enum

from pydantic import BaseModel, Field


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


class VisionResult(BaseModel):
    """Resultado del classifier de imágenes.

    `metadata` es libre porque cada categoría tiene atributos
    distintos (INE: ambos_lados, comprobante: fecha_dentro_60_dias, etc.).
    """

    category: VisionCategory
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict
