from __future__ import annotations

from types import SimpleNamespace

import pytest

from atendia.agent_runtime.respond_style_audio import (
    audio_tool_result,
    transcribe_audio_media,
)
from atendia.product_agents import agent_service_bridge as bridge


@pytest.mark.asyncio
async def test_audio_transcription_facts_become_citable_tool_result() -> None:
    class _FakeTranscriptions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "gpt-4o-mini-transcribe"
            assert kwargs["file"][0].endswith(".ogg")
            assert kwargs["file"][1] == b"audio-bytes"
            assert kwargs["file"][2] == "audio/ogg"
            return SimpleNamespace(text="quiero cotizar la renegada")

    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=_FakeTranscriptions())
    )

    facts = await transcribe_audio_media(
        api_key="k",
        audio_bytes=b"audio-bytes",
        mime_type="audio/ogg; codecs=opus",
        model="gpt-4o-mini-transcribe",
        client=client,
    )

    assert facts["transcribed"] is True
    assert facts["text"] == "quiero cotizar la renegada"
    result = audio_tool_result(facts)
    assert result["tool_name"] == "audio.transcribe"
    assert result["status"] == "succeeded"
    assert result["can_support_claims"] is True
    assert result["source_kind"] == "speech"


@pytest.mark.asyncio
async def test_bridge_audio_pretool_transcribes_approved_visible_candidate(
    tmp_path, monkeypatch
) -> None:
    rel = "tenant/audio.ogg"
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"audio-bytes")

    async def _fake_transcribe_audio_media(**kwargs):
        assert kwargs["audio_bytes"] == b"audio-bytes"
        assert kwargs["mime_type"] == "audio/ogg; codecs=opus"
        return {
            "transcribed": True,
            "text": "quiero saber cuanto doy de enganche",
            "mime_type": kwargs["mime_type"],
            "model": kwargs["model"],
            "confidence": None,
        }

    import atendia.agent_runtime.respond_style_audio as audio

    monkeypatch.setattr(audio, "transcribe_audio_media", _fake_transcribe_audio_media)
    monkeypatch.setattr(
        bridge,
        "get_settings",
        lambda: SimpleNamespace(
            upload_dir=str(tmp_path),
            respond_style_audio_transcription_timeout_s=1.0,
        ),
    )

    class _Session:
        async def get(self, model, key):
            return SimpleNamespace(
                metadata_json={
                    "media": {
                        "type": "audio",
                        "url": f"/uploads/{rel}",
                        "mime_type": "audio/ogg; codecs=opus",
                    }
                }
            )

    results, inbound_text, trace = await bridge._audio_pretool_results(
        _Session(),
        inbound_message_id="236c330b-74a1-43d7-a74a-1ed8fff2b22c",
        original_inbound_text="[nota de voz]",
        message_metadata={
            "media": {
                "type": "audio",
                "url": f"/uploads/{rel}",
                "mime_type": "audio/ogg; codecs=opus",
            }
        },
        api_key="k",
        model="gpt-4o-mini-transcribe",
        visible_send_candidate=True,
    )

    assert inbound_text == "quiero saber cuanto doy de enganche"
    assert trace["transcribed"] is True
    assert results[0]["tool_name"] == "audio.transcribe"
    assert results[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_bridge_audio_pretool_skips_outside_visible_candidate(monkeypatch) -> None:
    called = False

    async def _fake_transcribe_audio_media(**kwargs):
        nonlocal called
        called = True
        return {"transcribed": True, "text": "no debe correr"}

    import atendia.agent_runtime.respond_style_audio as audio

    monkeypatch.setattr(audio, "transcribe_audio_media", _fake_transcribe_audio_media)

    results, inbound_text, trace = await bridge._audio_pretool_results(
        SimpleNamespace(),
        inbound_message_id="236c330b-74a1-43d7-a74a-1ed8fff2b22c",
        original_inbound_text="[nota de voz]",
        message_metadata={
            "media": {
                "type": "audio",
                "url": "/uploads/tenant/audio.ogg",
                "mime_type": "audio/ogg",
            }
        },
        api_key="k",
        model="gpt-4o-mini-transcribe",
        visible_send_candidate=False,
    )

    assert called is False
    assert results == []
    assert inbound_text == "[nota de voz]"
    assert trace == {"attempted": False, "reason": "not_visible_candidate"}
