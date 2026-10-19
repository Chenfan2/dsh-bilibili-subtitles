"""Terminology replacement (product names, people, acronyms)."""

from __future__ import annotations

import json
import re
from pathlib import Path


class Glossary:
    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = dict(mapping or {})
        self._ordered = sorted(self.mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
        self._patterns: list[tuple[re.Pattern[str], str]] = []
        for source, target in self._ordered:
            if re.search(r"[A-Za-z]", source):
                self._patterns.append(
                    (re.compile(rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])", re.I), target)
                )

    @classmethod
    def from_file(cls, path: str | Path) -> "Glossary":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        mapping: dict[str, str] = {}
        if isinstance(data, dict):
            raw = data.get("terms", data)
            if isinstance(raw, dict):
                mapping = {str(k): str(v) for k, v in raw.items()}
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        mapping[str(item[0])] = str(item[1])
                    elif isinstance(item, dict) and item.get("from"):
                        mapping[str(item["from"])] = str(item.get("to", ""))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    mapping[str(item[0])] = str(item[1])
        return cls(mapping)

    def apply(self, text: str) -> str:
        if not text or not self.mapping:
            return text
        result = text
        # Latin terms first, with boundaries; then plain replacements.
        for pattern, target in self._patterns:
            result = pattern.sub(target, result)
        for source, target in self._ordered:
            if re.search(r"[A-Za-z]", source):
                continue
            if source in result:
                result = result.replace(source, target)
        return result

    def __bool__(self) -> bool:
        return bool(self.mapping)
