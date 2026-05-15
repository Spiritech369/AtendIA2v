"""Template helpers shared by NLU and Composer prompts.

`render_template`: substitute {{name}} placeholders. Raise on missing.
`_render_history`: render conversation history to chat-completions messages.
"""

import re

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, **vars: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in vars:
            raise RuntimeError(f"unsubstituted placeholder {{{{ {key} }}}} in template")
        return str(vars[key])

    return _PLACEHOLDER_RE.sub(_sub, template)


# Imported by both nlu_prompts and composer_prompts.
ROLE_LABELS = {
    "inbound": "cliente",
    "outbound": "asistente",
}


def _render_history(
    history: list[tuple[str, str]], history_format: str = "[{{role}}] {{text}}"
) -> list[dict[str, str]]:
    """Convert [(direction, text), ...] into chat-completions messages.

    inbound → role 'user', outbound → role 'assistant'. Bracketed Spanish label
    inside content uses ROLE_LABELS for transparency.
    """
    out: list[dict[str, str]] = []
    for direction, text in history:
        role = "user" if direction == "inbound" else "assistant"
        label = ROLE_LABELS.get(direction, direction)
        rendered = render_template(history_format, role=label, text=text)
        out.append({"role": role, "content": rendered})
    return out
