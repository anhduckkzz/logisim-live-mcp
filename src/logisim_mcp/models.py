from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    @classmethod
    def parse(cls, value: str | tuple[int, int] | list[int] | "Point") -> "Point":
        if isinstance(value, cls):
            return value
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return cls(int(value[0]), int(value[1]))
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("(") and text.endswith(")"):
                text = text[1:-1]
            parts = text.split(",")
            if len(parts) == 2:
                try:
                    return cls(int(parts[0].strip()), int(parts[1].strip()))
                except ValueError as exc:
                    raise ValueError(f"Invalid Logisim point: {value!r}") from exc
        raise ValueError(f"Invalid Logisim point: {value!r}; expected '(x,y)' or [x, y]")

    def __str__(self) -> str:
        return f"({self.x},{self.y})"

    def to_list(self) -> list[int]:
        return [self.x, self.y]


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    circuit: str | None = None
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

