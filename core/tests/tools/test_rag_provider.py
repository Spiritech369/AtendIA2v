import pytest

from atendia.config import get_settings
from atendia.tools.rag import get_provider
from atendia.tools.rag.mock_provider import MockProvider
from atendia.tools.rag.openai_provider import OpenAIProvider
from atendia.tools.rag.provider import PromptInput


@pytest.mark.asyncio
async def test_mock_embedding_deterministic():
    p = MockProvider()
    a = await p.create_embedding("¿Cuánto es el enganche?")
    b = await p.create_embedding("¿Cuánto es el enganche?")
    assert a == b
    assert len(a) == 3072


@pytest.mark.asyncio
async def test_mock_embedding_different_for_different_text():
    p = MockProvider()
    a = await p.create_embedding("foo")
    b = await p.create_embedding("bar")
    assert a != b


@pytest.mark.asyncio
async def test_mock_embedding_normalized():
    p = MockProvider()
    v = await p.create_embedding("hola")
    norm = sum(x * x for x in v) ** 0.5
    assert 0.99 < norm < 1.01, norm


@pytest.mark.asyncio
async def test_mock_embedding_handles_whitespace_and_case_consistently():
    p = MockProvider()
    a = await p.create_embedding("  Hola Mundo  ")
    b = await p.create_embedding("hola mundo")
    assert a == b


def test_get_provider_returns_mock_when_no_key(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "")
    monkeypatch.setenv("ATENDIA_V2_KB_PROVIDER", "openai")
    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        assert isinstance(get_provider(), MockProvider)
    finally:
        get_settings.cache_clear()
        get_provider.cache_clear()


def test_get_provider_returns_mock_when_kb_provider_set_to_mock(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-fake-but-set")
    monkeypatch.setenv("ATENDIA_V2_KB_PROVIDER", "mock")
    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        assert isinstance(get_provider(), MockProvider)
    finally:
        get_settings.cache_clear()
        get_provider.cache_clear()


def test_get_provider_returns_openai_when_key_present(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-fake-but-set")
    monkeypatch.setenv("ATENDIA_V2_KB_PROVIDER", "openai")
    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        assert isinstance(get_provider(), OpenAIProvider)
    finally:
        get_settings.cache_clear()
        get_provider.cache_clear()


@pytest.mark.asyncio
async def test_mock_generate_answer_includes_context_snippet():
    p = MockProvider()
    out = await p.generate_answer(
        PromptInput(
            system="sys",
            user="¿enganche?",
            context="<fuente type=faq>desde 10%</fuente>",
            response_instructions="responde",
            model="mock-model",
            max_tokens=100,
            temperature=0.0,
        )
    )
    assert "fuente" in out.text.lower() or "desde 10%" in out.text
    assert out.cost_usd == 0.0
    assert out.raw_response == {"mock": True}
