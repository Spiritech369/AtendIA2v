"""Markdown → WhatsApp normalization: markup only, wording untouched."""

from atendia.agent_runtime.respond_style_whatsapp_format import to_whatsapp_text


def test_bold_double_to_single_asterisk() -> None:
    assert (
        to_whatsapp_text("Tu plan sería **10% Nómina en Tarjeta**.")
        == "Tu plan sería *10% Nómina en Tarjeta*."
    )


def test_markdown_link_to_plain_url() -> None:
    assert (
        to_whatsapp_text("Mira el [Catálogo web](https://dinamomotos.com/catalogo)")
        == "Mira el Catálogo web: https://dinamomotos.com/catalogo"
    )


def test_headers_stripped_and_plain_text_untouched() -> None:
    assert to_whatsapp_text("## Requisitos\n- INE") == "Requisitos\n- INE"
    plain = "Hola, soy Francisco de Dinamo Motos. ¿Qué andas buscando?"
    assert to_whatsapp_text(plain) == plain
    assert to_whatsapp_text("") == ""
    assert to_whatsapp_text(None) is None


def test_single_asterisk_whatsapp_bold_preserved() -> None:
    assert to_whatsapp_text("plan *Nómina Tarjeta* listo") == "plan *Nómina Tarjeta* listo"
