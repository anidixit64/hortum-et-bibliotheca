"""Hand fixes for answer lines, kept in git so a rebuilt corpus.db never loses them."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class AnswerOverride:
    line_key: str
    answer_text: str  # for humans reading the file; the key is what matches
    main: str
    exclude: bool = False  # not a usable answer (junk, multi-part, etc.)
    saved_at: str = ""


class OverrideStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, AnswerOverride] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = AnswerOverride(**json.loads(line))
                    self._items[record.line_key] = record

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: str) -> AnswerOverride | None:
        return self._items.get(key)

    def all(self) -> list[AnswerOverride]:
        return list(self._items.values())

    def save(self, override: AnswerOverride) -> None:
        override.saved_at = datetime.now(UTC).isoformat(timespec="seconds")
        self._items[override.line_key] = override
        self._write()

    def remove(self, key: str) -> None:
        if self._items.pop(key, None) is not None:
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(asdict(item), ensure_ascii=False, sort_keys=True)
            for item in sorted(self._items.values(), key=lambda o: o.line_key)
        ]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(self.path)
