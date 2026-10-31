from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import LogisimMcpError, ProjectNotOpenError
from .live import LiveAppError, LiveAppUnavailable
from .live_sync import (
    LiveNotOpen,
    LiveRejected,
    LiveSession,
    LiveStale,
    capture,
    diff_ops,
)
from .project import LogisimProject
from .security import PathPolicy


class ProjectService:
    """Stateful project session with allowlisting, backups and atomic persistence."""

    def __init__(self, allowed_root: str | Path, *, live: LiveSession | None = None):
        self.policy = PathPolicy(allowed_root)
        self.project: LogisimProject | None = None
        self._lock = threading.RLock()
        self.live = live

    def _replaced_project_info(self) -> dict[str, Any] | None:
        """What happens to the project that is about to be replaced by open/create."""
        if self.project is None:
            return None
        info: dict[str, Any] = {
            "path": self.policy.relative(self.project.path),
            "had_unsaved_changes": bool(self.project.dirty),
        }
        if self.project.dirty:
            info["warning"] = (
                "The previously open project had edits that were never saved to disk and the "
                "bridge no longer holds them; they may still exist in its Logisim window."
            )
        return info

    @property
    def runtime_dir(self) -> Path:
        return self.policy.root / ".logisim-mcp" / "runtime"

    # ------------------------------------------------------------------ live window binding

    def _live_bound(self) -> LiveSession | None:
        if self.live is not None and self.live.bound and self.project is not None:
            if self.live.path == self.project.path:
                return self.live
            self.live.unbind()
        return None

    def _bind_to_window(self, path: Path, *, show: bool, reload: bool = False) -> dict[str, Any]:
        """Attach the open project to the same project in Logisim, opening it there if asked."""
        assert self.live is not None and self.project is not None
        info: dict[str, Any] = {}
        if show:
            info = self.live.runner.open_project(path, reload=reload)
        self.live.bind(path)
        if self.live.bound and not reload:
            # The window may show an older state than the file (edited elsewhere); check it
            # without disturbing undo history, and reload only when they really differ.
            try:
                check = self.live.saved(self.project) if not self.project.dirty else None
            except (LiveAppUnavailable, LiveAppError, LogisimMcpError):
                check = None
            if check is not None and check.get("open_in_app", True) and not check.get("verified"):
                info = self.live.runner.open_project(path, force_reload=True)
                self.live.bind(path)
                info["resynced_from_file"] = check.get("mismatches", [])
        info["live_editing"] = self.live.bound
        return info

    def open_project(
        self, path: str | Path, *, show_in_app: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            resolved = self.policy.resolve(path, suffixes=(".circ",))
            previous = self._replaced_project_info()
            pulled = False
            live_info: dict[str, Any] | None = None
            if self.live is not None:
                self.live.unbind()
                self.live.path = resolved
                status = self.live.status()
                if status and status.get("dirty"):
                    # The window holds unsaved hand edits: start from what the user sees.
                    self.live.bind(resolved, status)
                    self.project = self.live.pull(self.runtime_dir, resolved)
                    pulled = True
                else:
                    self.live.unbind()
                    self.project = LogisimProject.load(resolved)
                if show_in_app or status:
                    live_info = self._bind_to_window(resolved, show=show_in_app)
            else:
                self.project = LogisimProject.load(resolved)
            issues = [i.to_dict() for i in self.project.validate()]
            result = self.project.summary()
            result["path"] = self.policy.relative(resolved)
            result["validation"] = issues
            if previous is not None:
                result["previous_project"] = previous
            if self.live is not None:
                result["logisim_window"] = {
                    **(live_info or {"live_editing": False}),
                    "pulled_unsaved_window_edits": pulled,
                }
            return result

    def fresh_project(self) -> LogisimProject:
        """The open project, first absorbing any hand edits made in the Logisim window."""
        with self._lock:
            project = self.require_project()
            live = self._live_bound()
            if live is not None and live.has_external_changes() is not None:
                self.project = live.pull(self.runtime_dir, project.path)
            return self.require_project()

    def live_session(self) -> LiveSession:
        """The Logisim window binding, attaching (or opening) the window when needed."""
        with self._lock:
            project = self.fresh_project()
            live = self._live_bound()
            if live is not None:
                return live
            if self.live is None:
                raise LogisimMcpError("Live Logisim features are not available in this mode")
            if project.dirty:
                raise LogisimMcpError(
                    "The project has unsaved edits that are not shown in Logisim; call "
                    "save_and_open_in_logisim first"
                )
            self._bind_to_window(project.path, show=True)
            if not self.live.bound:
                raise LogisimMcpError("Could not attach to the Logisim window")
            return self.live

    def geometry(self, circuit: str, project: LogisimProject | None = None):
        """Exact geometry resolver when a Logisim window is attached, otherwise None."""
        from .geometry import GeometryResolver

        live = self._live_bound()
        if live is None:
            return None
        return GeometryResolver(live, project or self.require_project(), circuit)

    def edit(
        self,
        label: str,
        change,
        *,
        scope: list[str] | None = None,
        rename: tuple[str, str] | None = None,
    ) -> Any:
        """Run one semantic edit and mirror it into the Logisim window as one undoable action.

        ``change`` receives the project and performs the edit. ``scope`` limits the diff to
        the named circuits (circuit additions, removals and renames are always detected).
        """
        with self._lock:
            for attempt in range(2):
                project = self.require_project()
                live = self._live_bound()
                snapshot_tree = copy.deepcopy(project.tree)
                snapshot_dirty = project.dirty
                before = capture(project, scope) if live else None
                try:
                    result = change(project)
                except Exception:
                    # Batches must be all-or-nothing, even without a Logisim window.
                    project.tree = snapshot_tree
                    project.dirty = snapshot_dirty
                    raise
                if live is None:
                    return result
                if rename:
                    scope_after = [rename[1] if n == rename[0] else n for n in scope] if scope else None
                else:
                    scope_after = scope
                ops = diff_ops(before, capture(project, scope_after), rename=rename)
                if not ops:
                    return self._annotate(result, {"mirrored": True, "changes": 0})
                try:
                    response = live.apply(ops, label)
                except LiveStale:
                    project.tree = snapshot_tree
                    project.dirty = snapshot_dirty
                    if attempt:
                        raise LogisimMcpError(
                            "The Logisim window keeps changing; try the edit again"
                        ) from None
                    self.project = live.pull(self.runtime_dir, project.path)
                    continue
                except LiveRejected as exc:
                    project.tree = snapshot_tree
                    project.dirty = snapshot_dirty
                    raise LogisimMcpError(f"Logisim rejected this edit: {exc}") from None
                except LiveAppError as exc:
                    # Logisim failed internally; the plugin already undid its part.
                    project.tree = snapshot_tree
                    project.dirty = snapshot_dirty
                    raise LogisimMcpError(f"Logisim could not apply this edit: {exc}") from None
                except (LiveNotOpen, LiveAppUnavailable) as exc:
                    live.unbind()
                    return self._annotate(
                        result, {"mirrored": False, "reason": f"Logisim window unavailable: {exc}"}
                    )
                info: dict[str, Any] = {"mirrored": True}
                if response.get("warnings"):
                    info["warnings"] = response["warnings"]
                return self._annotate(result, info)
            raise LogisimMcpError("unreachable")

    @staticmethod
    def _annotate(result: Any, info: dict[str, Any]) -> Any:
        if isinstance(result, dict):
            result["logisim_window"] = info
        return result

    def create_project(
        self,
        path: str | Path,
        *,
        main_circuit: str = "main",
        overwrite: bool = False,
        show_in_app: bool = False,
    ) -> dict[str, Any]:
        """Create and atomically persist a native v5.0.0 project under the allowlist."""
        with self._lock:
            resolved = self.policy.resolve(path, must_exist=False, suffixes=(".circ",))
            if not resolved.parent.is_dir():
                raise FileNotFoundError(f"Parent directory does not exist: {resolved.parent}")
            if resolved.exists() and not overwrite:
                raise FileExistsError(f"Project already exists: {self.policy.relative(resolved)}")
            previous = self._replaced_project_info()
            if self.live is not None:
                self.live.unbind()
            self.project = LogisimProject.create(resolved, main_circuit)
            saved = self.save()
            if self.live is not None and show_in_app:
                saved["logisim_window"] = self._bind_to_window(resolved, show=True, reload=True)
            result = self.project.summary()
            result.update(
                {
                    "created": True,
                    "path": self.policy.relative(resolved),
                    "save": saved,
                }
            )
            if previous is not None:
                result["previous_project"] = previous
            return result

    def require_project(self) -> LogisimProject:
        if self.project is None:
            raise ProjectNotOpenError("No project is open; call open_project first")
        return self.project

    def close_project(self) -> dict[str, Any]:
        with self._lock:
            if self.project is None:
                return {"closed": False, "reason": "no project was open"}
            path = self.policy.relative(self.project.path)
            dirty = self.project.dirty
            self.project = None
            if self.live is not None:
                self.live.unbind()
            return {"closed": True, "path": path, "unsaved_changes_discarded": dirty}

    @property
    def backup_root(self) -> Path:
        root = self.policy.root / ".logisim-mcp" / "backups"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _backup_dir_for(self, source: Path) -> Path:
        relative = source.relative_to(self.policy.root)
        return self.backup_root / relative.parent / relative.stem

    def _backup_path_for(self, source: Path) -> Path:
        target_dir = self._backup_dir_for(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        return target_dir / f"{stamp}-{uuid.uuid4().hex[:8]}.circ"

    @staticmethod
    def _backup_keep() -> int:
        """How many automatic backups to retain per project (0 keeps everything)."""
        raw = os.environ.get("LOGISIM_MCP_BACKUP_KEEP", "20").strip()
        try:
            return max(0, int(raw))
        except ValueError:
            return 20

    def _create_backup(
        self, source: Path, *, reason: str, dedupe: bool = False
    ) -> dict[str, Any] | None:
        """Copy ``source`` into the backup folder.

        Automatic backups (``dedupe=True``) are skipped when the newest backup already holds
        identical bytes, and the oldest automatic ones are pruned beyond the retention limit.
        Backups the person asked for explicitly are always created and never pruned.
        """
        if not source.exists():
            return None
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if dedupe:
            newest = self._newest_backup(source)
            if newest is not None and newest.get("sha256") == digest:
                return {**newest, "reused": True}
        destination = self._backup_path_for(source)
        shutil.copy2(source, destination)
        metadata = {
            "backup": self.policy.relative(destination),
            "source": self.policy.relative(source),
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
            "sha256": digest,
        }
        destination.with_suffix(".json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        if dedupe:
            self._prune_backups(source)
        return metadata

    def _newest_backup(self, source: Path) -> dict[str, Any] | None:
        directory = self._backup_dir_for(source)
        if not directory.exists():
            return None
        files = sorted(directory.glob("*.circ"))
        if not files:
            return None
        newest = files[-1]
        meta_path = newest.with_suffix(".json")
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(metadata, dict) and metadata.get("sha256"):
                return metadata
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "backup": self.policy.relative(newest),
            "sha256": hashlib.sha256(newest.read_bytes()).hexdigest(),
        }

    def _prune_backups(self, source: Path) -> None:
        keep = self._backup_keep()
        if keep <= 0:
            return
        directory = self._backup_dir_for(source)
        automatic: list[Path] = []
        for path in sorted(directory.glob("*.circ")):
            try:
                reason = str(json.loads(path.with_suffix(".json").read_text(encoding="utf-8")).get("reason", ""))
            except (OSError, json.JSONDecodeError, AttributeError):
                continue  # unknown provenance: never delete
            if reason.startswith("pre-"):
                automatic.append(path)
        for path in automatic[: max(0, len(automatic) - keep)]:
            for victim in (path, path.with_suffix(".json")):
                try:
                    victim.unlink()
                except OSError:
                    pass

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def save(self) -> dict[str, Any]:
        with self._lock:
            project = self.require_project()
            live = self._live_bound()
            pulled = False
            if live is not None and live.has_external_changes() is not None:
                self.project = project = live.pull(self.runtime_dir, project.path)
                pulled = True
            project.assert_valid()
            data = project.serialize()
            backup = self._create_backup(project.path, reason="pre-save", dedupe=True)
            self._atomic_write(project.path, data)
            project.original_bytes = data
            project.dirty = False
            result: dict[str, Any] = {
                "saved": True,
                "path": self.policy.relative(project.path),
                "bytes": len(data),
                "backup": backup,
            }
            if self.live is not None:
                result["logisim_window"] = self._sync_window_after_write(project.path, pulled)
            return result

    def save_project_as(self, path: str | Path, *, overwrite: bool = False) -> dict[str, Any]:
        """Write the open project to a new .circ file and continue working on that file.

        The original file is left exactly as it is on disk, so this is the way to fork a
        variant without disturbing the source project.
        """
        with self._lock:
            project = self.require_project()
            live = self._live_bound()
            if live is not None and live.has_external_changes() is not None:
                self.project = project = live.pull(self.runtime_dir, project.path)
            resolved = self.policy.resolve(path, must_exist=False, suffixes=(".circ",))
            if not resolved.parent.is_dir():
                raise FileNotFoundError(f"Parent directory does not exist: {resolved.parent}")
            if resolved == project.path:
                raise ValueError("The target is the open project; use save_project instead")
            if resolved.exists() and not overwrite:
                raise FileExistsError(
                    f"Project already exists: {self.policy.relative(resolved)}; pass overwrite=true"
                )
            project.assert_valid()
            data = project.serialize()
            backup = self._create_backup(resolved, reason="pre-save-as", dedupe=True)
            self._atomic_write(resolved, data)
            previous = project.path
            project.path = resolved
            project.original_bytes = data
            project.dirty = False
            if self.live is not None:
                self.live.unbind()
            return {
                "saved": True,
                "path": self.policy.relative(resolved),
                "previous_path": self.policy.relative(previous),
                "original_file_unchanged": True,
                "bytes": len(data),
                "backup": backup,
                "logisim_window": {
                    "live_editing": False,
                    "hint": "Call save_and_open_in_logisim to view the new file in Logisim",
                },
            }

    def _sync_window_after_write(self, path: Path, pulled: bool) -> dict[str, Any]:
        """Make the Logisim window agree with the file that was just written."""
        assert self.live is not None and self.project is not None
        live = self._live_bound()
        if live is None:
            # Not bound (e.g. opened by hand): reload it there if it happens to be open.
            try:
                reloaded = self.live.client.reload_if_open(path)
            except (LiveAppUnavailable, LiveAppError) as exc:
                return {"synced": False, "reason": str(exc)}
            if reloaded.get("open_in_app"):
                self.live.bind(path)
                return {"synced": True, "method": "reloaded", "live_editing": self.live.bound}
            return {"synced": False, "reason": "project is not open in Logisim"}
        try:
            check = live.saved(self.project)
        except (LiveAppUnavailable, LiveNotOpen, LiveAppError) as exc:
            live.unbind()
            return {"synced": False, "reason": str(exc)}
        if not check.get("open_in_app", True):
            live.unbind()
            return {"synced": False, "reason": "project was closed in Logisim"}
        if check.get("verified"):
            return {"synced": True, "method": "verified_in_place", "pulled_window_edits": pulled}
        reopened = live.runner.open_project(path, force_reload=True)
        live.bind(path)
        return {
            "synced": True,
            "method": "reloaded",
            "mismatches": check.get("mismatches", []),
            "mode": reopened.get("mode"),
        }

    def validate(self) -> dict[str, Any]:
        project = self.require_project()
        issues = [issue.to_dict() for issue in project.validate()]
        return {
            "valid": not any(issue["severity"] == "error" for issue in issues),
            "issues": issues,
        }

    def list_backups(self) -> list[dict[str, Any]]:
        project = self.require_project()
        backup_dir = self._backup_dir_for(project.path)
        if not backup_dir.exists():
            return []
        result = []
        for path in sorted(backup_dir.glob("*.circ"), reverse=True):
            meta_path = path.with_suffix(".json")
            if meta_path.exists():
                try:
                    result.append(json.loads(meta_path.read_text(encoding="utf-8")))
                    continue
                except (json.JSONDecodeError, OSError):
                    pass
            result.append({"backup": self.policy.relative(path)})
        return result

    def create_backup(self, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            project = self.require_project()
            backup = self._create_backup(project.path, reason=reason)
            if backup is None:
                raise FileNotFoundError(f"Project file does not exist: {project.path}")
            return backup

    def rollback(self, backup_path: str | Path) -> dict[str, Any]:
        with self._lock:
            project = self.require_project()
            backup = self.policy.resolve(backup_path, suffixes=(".circ",))
            expected_dir = self._backup_dir_for(project.path).resolve()
            try:
                backup.relative_to(expected_dir)
            except ValueError:
                raise ValueError(
                    "Rollback source must be a bridge backup for the currently open project"
                ) from None
            candidate = LogisimProject.load(backup)
            candidate.assert_valid()
            safety_backup = self._create_backup(project.path, reason="pre-rollback", dedupe=True)
            self._atomic_write(project.path, backup.read_bytes())
            self.project = LogisimProject.load(project.path)
            window: dict[str, Any] | None = None
            if self.live is not None:
                try:
                    reloaded = self.live.client.reload_if_open(project.path, force=True)
                    if reloaded.get("open_in_app"):
                        self.live.bind(project.path)
                    window = {"synced": bool(reloaded.get("open_in_app"))}
                except (LiveAppUnavailable, LiveAppError) as exc:
                    self.live.unbind()
                    window = {"synced": False, "reason": str(exc)}
            return {
                "logisim_window": window,
                "rolled_back": True,
                "path": self.policy.relative(project.path),
                "restored_from": self.policy.relative(backup),
                "safety_backup": safety_backup,
            }
