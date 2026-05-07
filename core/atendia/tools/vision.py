"""OpenAI Vision API wrapper (Phase 3c.2).

Clasifica imágenes en una de 9 categorías (7 docs + moto + unrelated)
para DOC MODE. Análogo a tools/embeddings.py — cost tracking
end-to-end, structured outputs (JSON schema) para determinismo.

Sin sesgo de `expected_doc`: clasificación absoluta.
"""
import json
import time
from decimal import Decimal

from openai import AsyncOpenAI

from atendia.contracts.vision_result import VisionCategory, VisionResult

# gpt-4o pricing as of 2026-05:
# - $2.50 per 1M input tokens (text + image)
# - $10.00 per 1M output tokens
VISION_PRICE_PER_1M_INPUT_TOKENS: Decimal = Decimal("2.50")
VISION_PRICE_PER_1M_OUTPUT_TOKENS: Decimal = Decimal("10.00")
DEFAULT_VISION_MODEL: str = "gpt-4o"


_VISION_JSON_SCHEMA = {
    "name": "vision_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": [c.value for c in VisionCategory],
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "metadata": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ambos_lados": {"type": "boolean"},
                    "legible": {"type": "boolean"},
                    "fecha_iso": {"type": ["string", "null"]},
                    "institucion": {"type": ["string", "null"]},
                    "modelo": {"type": ["string", "null"]},
                    "notas": {"type": ["string", "null"]},
                },
                "required": ["ambos_lados", "legible", "fecha_iso",
                             "institucion", "modelo", "notas"],
            },
        },
        "required": ["category", "confidence", "metadata"],
        "additionalProperties": False,
    },
}


_SYSTEM_PROMPT = """\
Eres un clasificador de imágenes para una concesionaria de motocicletas
en México. Recibes una imagen y devuelves JSON con tres campos:

  - category: una de [ine, comprobante, recibo_nomina, estado_cuenta,
              constancia_sat, factura, imss, moto, unrelated]
  - confidence: tu certeza en [0.0, 1.0]
  - metadata: dict con los siguientes campos (siempre todos, null si no aplica):
      * ambos_lados (bool): para INE, true si se ven ambos lados
      * legible (bool): true si el texto principal se lee con claridad
      * fecha_iso (str|null): fecha visible en formato ISO si aplica (recibos, comprobantes)
      * institucion (str|null): banco / SAT / IMSS / proveedor de servicio si aplica
      * modelo (str|null): modelo de moto si category == moto
      * notas (str|null): observación libre corta

Reglas:
- Sé objetivo: clasifica lo que VES en la imagen, no lo que crees que el usuario quiso mandar.
- "ine" solo si claramente es una credencial INE (México). Si es licencia o pasaporte → "unrelated".
- "comprobante" para recibos de luz/agua/gas/internet con dirección visible.
- "moto" para foto de motocicleta (no scooter eléctrico ni bici).
- "unrelated" para selfies, screenshots, paisajes, comida, cualquier otra cosa.
- confidence < 0.5 si la imagen está borrosa, oscura o muy alejada.
"""


async def classify_image(
    *,
    client: AsyncOpenAI,
    image_url: str,
    model: str = DEFAULT_VISION_MODEL,
) -> tuple[VisionResult, int, int, Decimal, int]:
    """Classify a single image.

    Returns (result, tokens_in, tokens_out, cost_usd, latency_ms).
    """
    started = time.perf_counter()
    resp = await client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Clasifica esta imagen."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
        response_format={"type": "json_schema", "json_schema": _VISION_JSON_SCHEMA},
        temperature=0,
    )
    raw = json.loads(resp.choices[0].message.content)
    result = VisionResult.model_validate(raw)
    tokens_in = resp.usage.prompt_tokens
    tokens_out = resp.usage.completion_tokens
    cost = _compute_cost(tokens_in, tokens_out)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return result, tokens_in, tokens_out, cost, latency_ms


def _compute_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """gpt-4o vision pricing: $2.50/1M input + $10.00/1M output, quantized."""
    in_cost = Decimal(tokens_in) * VISION_PRICE_PER_1M_INPUT_TOKENS / Decimal("1000000")
    out_cost = Decimal(tokens_out) * VISION_PRICE_PER_1M_OUTPUT_TOKENS / Decimal("1000000")
    return (in_cost + out_cost).quantize(Decimal("0.000001"))
