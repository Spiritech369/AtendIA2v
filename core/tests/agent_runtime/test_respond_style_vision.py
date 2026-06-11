from __future__ import annotations

from types import SimpleNamespace

import pytest

from atendia.agent_runtime.respond_style_vision import (
    analyze_document_media,
    vision_tool_result,
)


@pytest.mark.asyncio
async def test_unsupported_media_returns_marker_without_calling_api() -> None:
    facts = await analyze_document_media(
        api_key="k", image_bytes=b"x", mime_type="application/pdf"
    )
    assert facts == {
        "reviewed": False,
        "reason": "unsupported_media_type",
        "mime_type": "application/pdf",
    }
    result = vision_tool_result(facts)
    assert result["status"] == "skipped"
    assert result["can_support_claims"] is False
    assert result["source_kind"] == "vision"


@pytest.mark.asyncio
async def test_vision_facts_become_citable_tool_result(monkeypatch) -> None:
    import openai

    payload = (
        '{"document_type": "identificacion_oficial", "legible": true, '
        '"summary": "Identificacion oficial por el frente.", '
        '"visible_fields": {"vigencia_visible": true}, "confidence": 0.9}'
    )

    class _FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "gpt-4o"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
            )

    class _FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    facts = await analyze_document_media(
        api_key="k", image_bytes=b"jpegbytes", mime_type="image/jpeg"
    )
    assert facts["reviewed"] is True
    assert facts["document_type"] == "identificacion_oficial"

    result = vision_tool_result(facts)
    assert result["tool_name"] == "document.review"
    assert result["status"] == "succeeded"
    assert result["can_support_claims"] is True
    assert result["source_refs"] == ["document.review"]


@pytest.mark.asyncio
async def test_vision_failure_never_raises(monkeypatch) -> None:
    import openai

    class _Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("no network")

    monkeypatch.setattr(openai, "AsyncOpenAI", _Boom)
    facts = await analyze_document_media(
        api_key="k", image_bytes=b"x", mime_type="image/png"
    )
    assert facts["reviewed"] is False
    assert facts["reason"].startswith("vision_failed")


def test_builder_injects_pretool_results_into_context() -> None:
    from atendia.agent_runtime.respond_style_context_builder import (
        RespondStyleContextPackageBuilder,
        RespondStyleContextSnapshot,
    )

    snapshot = RespondStyleContextSnapshot(
        tenant_id="t",
        agent_id="a",
        agent_version_id="v",
        conversation_id="c",
        inbound_text="[imagen]",
        pretool_results=[
            {
                "tool_name": "document.review",
                "status": "succeeded",
                "facts": {"document_type": "identificacion_oficial"},
                "source_kind": "vision",
            }
        ],
    )
    built = RespondStyleContextPackageBuilder().build(snapshot)
    results = built.context_package.tool_results
    assert len(results) == 1
    assert results[0]["tool_name"] == "document.review"
    assert results[0]["source_kind"] == "vision"
