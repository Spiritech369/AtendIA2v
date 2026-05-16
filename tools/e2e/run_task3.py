"""Task 3 launcher — KB ingestion + retrieval + agent scoping.

Kept as a separate tiny entrypoint (NOT under core/, which is a watched
uvicorn --reload bind-mount) so the Task 2 `main()` in e2e_setup.py stays
untouched. Run with the core venv (it has httpx):

  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 uv run python "../tools/e2e/run_task3.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_setup import run_task3  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_task3())
