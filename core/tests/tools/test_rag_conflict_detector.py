from atendia.tools.rag.conflict_detector import ChunkLike, detect_conflicts_in_results


def _c(text: str, source_id: str = "x", source_type: str = "faq") -> ChunkLike:
    return ChunkLike(text=text, source_type=source_type, source_id=source_id)


def test_price_mismatch_same_sku() -> None:
    a = _c("Modelo Dinamo U5 — precio $45,000 MXN", source_id="a")
    b = _c("Modelo Dinamo U5 — precio $48,500 MXN", source_id="b")
    conflicts = detect_conflicts_in_results([a, b])
    assert any(c.detection_type == "price_mismatch" for c in conflicts)


def test_enum_disagreement_enganche() -> None:
    a = _c("Enganche desde 10% según el plan", source_id="a")
    b = _c("Enganche mínimo 15% para nómina efectivo", source_id="b")
    conflicts = detect_conflicts_in_results([a, b])
    assert any(c.detection_type == "enum_disagreement" for c in conflicts)


def test_text_overlap_with_negation() -> None:
    a = _c("No es necesario comprobar ingresos para tu crédito", source_id="a")
    b = _c("Es necesario comprobar ingresos para tu crédito", source_id="b")
    conflicts = detect_conflicts_in_results([a, b])
    assert any(c.detection_type == "text_overlap_with_negation" for c in conflicts)


def test_no_conflicts_when_consistent() -> None:
    a = _c("Enganche desde 10%", source_id="a")
    b = _c("Enganche desde 10% en todas las modalidades", source_id="b")
    assert detect_conflicts_in_results([a, b]) == []


def test_no_conflict_for_single_chunk() -> None:
    a = _c("Modelo X — precio $45,000", source_id="a")
    assert detect_conflicts_in_results([a]) == []


def test_price_mismatch_excerpts_shown() -> None:
    a = _c("Precio $45,000", source_id="a")
    b = _c("Precio $48,500", source_id="b")
    conflicts = detect_conflicts_in_results([a, b])
    pm = [c for c in conflicts if c.detection_type == "price_mismatch"]
    assert pm
    assert "$45,000" in pm[0].entity_a_excerpt
    assert "$48,500" in pm[0].entity_b_excerpt


def test_negation_only_flags_when_jaccard_high_enough() -> None:
    # Two short sentences with one negation but very low overlap → no conflict.
    a = _c("La marca azul vende coches usados", source_id="a")
    b = _c("No tenemos servicio de pintura", source_id="b")
    assert detect_conflicts_in_results([a, b]) == []
