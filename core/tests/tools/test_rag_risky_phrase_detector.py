from atendia.tools.rag.risky_phrase_detector import (
    DEFAULT_RISKY_PHRASES,
    detect_risky_phrases,
)


def test_each_default_pattern_fires_against_a_canonical_match() -> None:
    samples = {
        r"crédito\s+aprobado": "Tu crédito aprobado al 100%.",
        r"aprobado\s+seguro": "Es un trato aprobado seguro.",
        r"sin\s+revisar\s+buró": "Funciona sin revisar buró de crédito.",
        r"entrega\s+garantizada": "Entrega garantizada en 24h.",
        r"precio\s+fijo": "Tenemos precio fijo todo el año.",
        r"no\s+necesitas\s+comprobar\s+ingresos": "No necesitas comprobar ingresos.",
    }
    for entry in DEFAULT_RISKY_PHRASES:
        sample = samples[entry["pattern"]]
        risks = detect_risky_phrases(sample)
        assert any(r.pattern == entry["pattern"] for r in risks), entry["pattern"]


def test_no_match_returns_empty() -> None:
    assert detect_risky_phrases("Texto neutral sin frases prohibidas.") == []


def test_custom_overrides_defaults() -> None:
    custom = [{"pattern": r"foo+", "rewrite": "bar"}]
    assert detect_risky_phrases("foooo", custom) and detect_risky_phrases("foooo", custom)[0].description == "bar"
    # And the default phrases don't fire when a custom list is provided.
    assert detect_risky_phrases("crédito aprobado", custom) == []


def test_case_insensitive_match() -> None:
    risks = detect_risky_phrases("CRÉDITO APROBADO HOY")
    assert any(r.pattern == r"crédito\s+aprobado" for r in risks)


def test_multiple_risks_returned_in_one_pass() -> None:
    text = "Tu crédito aprobado y entrega garantizada."
    risks = detect_risky_phrases(text)
    patterns = {r.pattern for r in risks}
    assert r"crédito\s+aprobado" in patterns
    assert r"entrega\s+garantizada" in patterns
