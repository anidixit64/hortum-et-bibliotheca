"""Hand-labeled clues worth knowing (pipeline/eval/labeled_clues.yaml), for scoring evals."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path("pipeline/eval/labeled_clues.yaml")


@dataclass(frozen=True)
class LabeledClue:
    fact: str
    match: tuple[str, ...]

    def found_in(self, text: str) -> bool:
        """Whole-word, case-insensitive match of any term ("Ras" must not match "grass")."""
        return any(
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
            for term in self.match
        )


@dataclass(frozen=True)
class LabeledTopic:
    id: str
    name: str
    clues: tuple[LabeledClue, ...]


def load(path: Path = DEFAULT_PATH) -> list[LabeledTopic]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        LabeledTopic(
            id=t["id"],
            name=t["name"],
            clues=tuple(
                LabeledClue(c["fact"], tuple(str(m) for m in c["match"])) for c in t["clues"]
            ),
        )
        for t in data["topics"]
    ]
