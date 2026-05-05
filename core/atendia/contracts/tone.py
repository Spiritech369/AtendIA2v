from typing import Literal

from pydantic import BaseModel, Field


class Tone(BaseModel):
    register: Literal["informal_mexicano", "formal_es", "neutral_es"] = "neutral_es"
    use_emojis: Literal["never", "sparingly", "frequent"] = "sparingly"
    max_words_per_message: int = Field(default=40, ge=10, le=120)
    bot_name: str = "Asistente"
    forbidden_phrases: list[str] = Field(default_factory=list)
    signature_phrases: list[str] = Field(default_factory=list)
