"""VisionResult — output del classifier de imágenes.

Sin sesgo: el clasificador NO recibe `expected_doc`; solo categoriza
en términos absolutos. La decisión "matchea lo que esperabamos" es
del runner.
"""

import pytest
from pydantic import ValidationError

from atendia.contracts.vision_result import VisionCategory, VisionResult


def test_vision_categories_cover_v1_doc_types() -> None:
    """Categorías esperadas cubren los 7 docs del v1 + moto + unrelated."""
    expected = {
        "ine",
        "comprobante",
        "recibo_nomina",
        "estado_cuenta",
        "constancia_sat",
        "factura",
        "imss",
        "moto",
        "unrelated",
    }
    actual = {c.value for c in VisionCategory}
    assert expected == actual


def test_vision_result_basic() -> None:
    r = VisionResult(category=VisionCategory.INE, confidence=0.92, metadata={})
    assert r.category == VisionCategory.INE


def test_vision_result_metadata_can_be_anything() -> None:
    """metadata es free-form dict (e.g., ambos_lados=True para INE)."""
    r = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": True, "legible": True},
    )
    assert r.metadata["ambos_lados"] is True


def test_vision_result_confidence_must_be_in_range() -> None:
    """confidence ∈ [0, 1]."""
    with pytest.raises(ValidationError):
        VisionResult(category=VisionCategory.MOTO, confidence=1.5, metadata={})
    with pytest.raises(ValidationError):
        VisionResult(category=VisionCategory.MOTO, confidence=-0.1, metadata={})
