from pathlib import Path

import yaml

from atendia.contracts.nlu_result import NLUResult


class CannedNLU:
    """Reads a list of NLUResult from a YAML file and returns them in order."""

    def __init__(self, fixture_path: Path) -> None:
        data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        self._queue = [NLUResult.model_validate(item) for item in data["nlu_results"]]
        self._idx = 0

    def next(self) -> NLUResult:
        if self._idx >= len(self._queue):
            raise IndexError("no more canned NLU results")
        result = self._queue[self._idx]
        self._idx += 1
        return result
