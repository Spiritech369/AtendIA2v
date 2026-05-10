from uuid import uuid4

from atendia.tools.rag.prompt_builder import (
    AGENT_PROMPTS,
    BASE_SYSTEM,
    SAFETY_BLOCK,
    build_prompt,
)
from atendia.tools.rag.retriever import RetrievedChunk, SafeAnswerSettings


def _chunk(text: str = "Enganche desde 10%", **overrides) -> RetrievedChunk:
    return RetrievedChunk(
        source_type=overrides.get("source_type", "faq"),
        source_id=overrides.get("source_id", uuid4()),
        text=text,
        score=overrides.get("score", 0.92),
        collection=overrides.get("collection", "credito"),
    )


def test_system_includes_base_agent_and_safety():
    p = build_prompt("¿Y el enganche?", "sales_agent", [_chunk()], SafeAnswerSettings())
    assert BASE_SYSTEM in p.system
    assert AGENT_PROMPTS["sales_agent"] in p.system
    assert SAFETY_BLOCK in p.system


def test_unknown_agent_still_includes_base_and_safety_blocks():
    p = build_prompt("hola", "unknown_role", [], SafeAnswerSettings())
    assert BASE_SYSTEM in p.system
    assert SAFETY_BLOCK in p.system


def test_chunks_serialized_inside_fuente_envelope():
    cid = uuid4()
    p = build_prompt(
        "?", "duda_general",
        [_chunk(source_id=cid, score=0.91, collection="requisitos")],
        SafeAnswerSettings(),
    )
    assert f"<fuente type=faq id={cid} collection=requisitos score=0.910>" in p.context
    assert "</fuente>" in p.context


def test_chunk_text_truncated_to_600():
    long = "A" * 2000
    p = build_prompt("q", "sales_agent", [_chunk(text=long)], SafeAnswerSettings())
    # 600 'A' chars inside the envelope
    assert "A" * 600 in p.context
    assert "A" * 601 not in p.context


def test_default_model_and_response_instructions():
    p = build_prompt("q", "duda_general", [], SafeAnswerSettings())
    assert p.model == "gpt-4o-mini"
    assert p.max_tokens == 400
    assert 0.0 < p.temperature <= 1.0
    assert "asesor" in p.response_instructions.lower()


def test_safety_block_is_last_so_injection_inside_agent_block_is_overridden():
    p = build_prompt("q", "sales_agent", [_chunk()], SafeAnswerSettings())
    # The safety block must appear AFTER the agent block in p.system so a
    # malicious agent prompt override can't disable safety.
    safety_pos = p.system.find(SAFETY_BLOCK)
    agent_pos = p.system.find(AGENT_PROMPTS["sales_agent"])
    assert safety_pos > agent_pos > 0
