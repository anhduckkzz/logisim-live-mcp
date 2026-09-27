from __future__ import annotations

from pathlib import Path

from .errors import PathNotAllowedError


class PathPolicy:
    """Resolve all user paths beneath one explicit, existing root."""

    def __init__(self, root: str | Path):
        resolved = Path(root).expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise PathNotAllowedError(f"Allowlisted root is not a directory: {resolved}")
        self.root = resolved

    def resolve(
        self,
        candidate: str | Path,
        *,
        must_exist: bool = True,
        suffixes: tuple[str, ...] | None = None,
    ) -> Path:
        raw = Path(candidate).expanduser()
        joined = raw if raw.is_absolute() else self.root / raw
        try:
            resolved = joined.resolve(strict=must_exist)
        except FileNotFoundError:
            raise PathNotAllowedError(f"Path does not exist inside allowlisted root: {candidate}") from None
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise PathNotAllowedError(
                f"Path is outside allowlisted root {self.root}: {candidate}"
            ) from None
        if suffixes and resolved.suffix.lower() not in suffixes:
            allowed = ", ".join(suffixes)
            raise PathNotAllowedError(f"Path must end in one of [{allowed}]: {candidate}")
        return resolved

    def relative(self, path: str | Path) -> str:
        return str(Path(path).resolve().relative_to(self.root))
