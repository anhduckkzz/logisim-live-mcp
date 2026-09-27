from __future__ import annotations

import os
import locale
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import LogisimMcpError
from .live import LiveAppClient, LiveAppError, LiveAppUnavailable, default_plugin_jar
from .security import PathPolicy

LIVE_PROTOCOL = "2"


class LogisimRunner:
    def __init__(
        self,
        policy: PathPolicy,
        executable: str | Path | None = None,
        java_executable: str | Path | None = None,
        *,
        live_client: LiveAppClient | None = None,
        plugin_jar: str | Path | None = None,
    ):
        configured = executable or os.environ.get("LOGISIM_EVOLUTION") or self.discover_executable()
        self.executable = Path(configured).expanduser().resolve() if configured else None
        self.java_executable = str(java_executable or os.environ.get("JAVA", "java"))
        self.policy = policy
        self._live = live_client
        self.plugin_jar = Path(plugin_jar).resolve() if plugin_jar else default_plugin_jar()

    @property
    def live(self) -> LiveAppClient:
        # Created lazily so plain CLI/test runs never touch the per-user state file.
        if self._live is None:
            self._live = LiveAppClient()
        return self._live

    @staticmethod
    def discover_executable() -> Path | None:
        for command in ("logisim-evolution", "logisim-evolution.exe", "logisim"):
            resolved = shutil.which(command)
            if resolved:
                return Path(resolved)
        candidates: list[Path] = []
        for variable in ("ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if not base:
                continue
            root = Path(base)
            candidates.extend(
                [
                    root / "Logisim-evolution" / "Logisim-evolution.exe",
                    root / "Logisim Evolution" / "Logisim-evolution.exe",
                    root / "Programs" / "Logisim-evolution" / "Logisim-evolution.exe",
                ]
            )
        candidates.extend(
            [
                Path.cwd() / "tools" / "logisim-evolution-5.0.0-all.jar",
                Path.cwd() / "tools" / "logisim-evolution.jar",
            ]
        )
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def build_command(
        self, circuit_name: str, vector_path: Path, project_path: Path
    ) -> list[str]:
        if self.executable is None:
            raise LogisimMcpError(
                "Logisim is not configured. Set LOGISIM_EVOLUTION to the Logisim Evolution JAR "
                "or pass --logisim when starting the server."
            )
        if not self.executable.exists():
            raise LogisimMcpError(f"Configured Logisim file does not exist: {self.executable}")
        args = [
            "--test-vector",
            circuit_name,
            str(vector_path),
            str(project_path),
        ]
        if self.executable.suffix.lower() == ".jar":
            return [self.java_executable, "-jar", str(self.executable), *args]
        return [str(self.executable), *args]

    def build_open_command(self, project_path: Path) -> list[str]:
        if self.executable is None:
            raise LogisimMcpError(
                "Logisim is not configured. Set LOGISIM_EVOLUTION to the Logisim Evolution "
                "5.0.0 JAR or pass --logisim when starting the server."
            )
        if not self.executable.exists():
            raise LogisimMcpError(f"Configured Logisim file does not exist: {self.executable}")
        args = ["--no-splash", str(project_path)]
        if self.executable.suffix.lower() == ".jar":
            return [self.java_executable, "-jar", str(self.executable), *args]
        return [str(self.executable), *args]

    def build_validation_command(self, project_path: Path, output_path: Path) -> list[str]:
        if self.executable is None:
            raise LogisimMcpError(
                "Logisim is not configured. Set LOGISIM_EVOLUTION to the Logisim Evolution "
                "5.0.0 JAR or pass --logisim when starting the server."
            )
        if not self.executable.exists():
            raise LogisimMcpError(f"Configured Logisim file does not exist: {self.executable}")
        args = ["--new-file-format", str(project_path), str(output_path)]
        if self.executable.suffix.lower() == ".jar":
            return [self.java_executable, "-jar", str(self.executable), *args]
        return [str(self.executable), *args]

    def validate_project_file(
        self, project_path: Path, *, timeout_seconds: int = 60
    ) -> dict[str, Any]:
        """Round-trip a saved file through Logisim's own v5 XML reader/writer."""
        resolved = self.policy.resolve(project_path, suffixes=(".circ",))
        runtime_root = self.policy.root / ".logisim-mcp" / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="validate-", dir=runtime_root) as temp_dir:
            output_path = Path(temp_dir) / "normalized.circ"
            command = self.build_validation_command(resolved, output_path)
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.policy.root,
                    capture_output=True,
                    text=True,
                    encoding=locale.getpreferredencoding(False),
                    errors="replace",
                    timeout=max(1, min(timeout_seconds, 300)),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LogisimMcpError(
                    f"Logisim validation timed out after {timeout_seconds} seconds"
                ) from exc
            stdout, stdout_suppressed = self._clean_output(completed.stdout)
            stderr, stderr_suppressed = self._clean_output(completed.stderr)
            return {
                "valid": completed.returncode == 0 and output_path.is_file(),
                "exit_code": completed.returncode,
                "normalized_file_created": output_path.is_file(),
                "stdout": stdout,
                "stderr": stderr,
                "suppressed_line_count": stdout_suppressed + stderr_suppressed,
            }

    def build_live_open_command(self, project_path: Path) -> tuple[list[str], dict[str, str]]:
        """Launch command plus extra environment that attaches the live plugin."""
        plugin = self.plugin_jar
        if plugin is None:
            return self.build_open_command(project_path), {}
        env = {
            "LOGISIM_MCP_LIVE_TOKEN": self.live.token,
            "LOGISIM_MCP_LAUNCH_FILE": str(project_path),
        }
        agent_option = f"-javaagent:{plugin}=port={self.live.port}"
        command = self.build_open_command(project_path)
        if self.executable is not None and self.executable.suffix.lower() == ".jar":
            # java [-javaagent:...] -jar logisim.jar --no-splash file.circ
            return [command[0], agent_option, *command[1:]], env
        # Native launchers (jpackage .exe) still start a JVM, which honours JAVA_TOOL_OPTIONS.
        existing = os.environ.get("JAVA_TOOL_OPTIONS", "")
        quoted = f'"{agent_option}"' if " " in agent_option else agent_option
        env["JAVA_TOOL_OPTIONS"] = f"{existing} {quoted}".strip()
        return command, env

    def live_status(self) -> dict[str, Any]:
        status = self.live.ping()
        return {
            "plugin_jar": str(self.plugin_jar) if self.plugin_jar else None,
            "port": self.live.port,
            "running": status is not None,
            "app": status,
        }

    def sync_running_app(self, project_path: Path, *, force: bool = False) -> dict[str, Any]:
        """Reload the project in the running app if (and only if) it is already open there."""
        resolved = self.policy.resolve(project_path, suffixes=(".circ",))
        try:
            return {"synced": True, **self.live.reload_if_open(resolved, force=force)}
        except LiveAppUnavailable:
            return {"synced": False, "reason": "Logisim is not running with the live plugin"}
        except LiveAppError as exc:
            return {"synced": False, "reason": exc.message, "code": exc.code}

    def open_project(
        self,
        project_path: Path,
        *,
        force_reload: bool = False,
        reload: bool = True,
        wait_seconds: float = 45.0,
    ) -> dict[str, Any]:
        """Show the saved project in Logisim end to end, without any prompt.

        * Logisim already running (with the plugin): reload the file in its existing window
          (or, with ``reload=False``, just bring it forward), or open it in that same
          application, and bring the window to the front.
        * Logisim closed: launch it with the plugin and the project, then wait until the
          window has actually loaded the file.
        """
        resolved = self.policy.resolve(project_path, suffixes=(".circ",))
        relative = self.policy.relative(resolved)
        try:
            running = self.live.ping()
        except LiveAppError:
            running = None  # e.g. wrong token; the OPEN below reports it precisely
        if running is not None and str(running.get("protocol", "1")) < LIVE_PROTOCOL:
            raise LogisimMcpError(
                "The open Logisim window was started by an older version of this bridge and "
                "cannot be edited live. Save your work in Logisim, close Logisim once, and call "
                "this tool again; the bridge will relaunch it with the current plugin."
            )
        try:
            result = self.live.open(resolved, force=force_reload, reload=reload)
            return {
                "opened": True,
                "mode": f"{result.get('action') or ('reloaded' if result.get('reloaded') else 'opened')}_in_running_app",
                "path": relative,
                **result,
            }
        except LiveAppUnavailable:
            pass
        except LiveAppError as exc:
            if exc.code == "DIRTY":
                raise LogisimMcpError(exc.message) from exc
            if exc.code == "AUTH":
                raise LogisimMcpError(
                    "A Logisim window launched by another bridge session holds the control port "
                    f"{self.live.port}. Close that Logisim window once and call this tool again."
                ) from exc
            raise LogisimMcpError(f"Logisim could not open the project: {exc.message}") from exc
        return self._launch(resolved, relative, wait_seconds=wait_seconds)

    def _launch(self, resolved: Path, relative: str, *, wait_seconds: float) -> dict[str, Any]:
        command, extra_env = self.build_live_open_command(resolved)
        env = {**os.environ, **extra_env}
        popen_kwargs: dict[str, Any] = {
            "cwd": self.policy.root,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
        }
        if os.name == "nt":
            base_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            # Break away from the MCP host's job object so closing the chat client does not
            # kill the Logisim window; fall back if the job forbids breakaway.
            flag_options = [base_flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), base_flags]
        else:
            popen_kwargs["start_new_session"] = True
            flag_options = [0]
        process = None
        last_error: OSError | None = None
        for flags in flag_options:
            try:
                if os.name == "nt":
                    popen_kwargs["creationflags"] = flags
                process = subprocess.Popen(command, **popen_kwargs)
                break
            except OSError as exc:
                last_error = exc
        if process is None:
            raise LogisimMcpError(f"Could not launch Logisim Evolution: {last_error}")

        if self.plugin_jar is None:
            time.sleep(0.5)
            if process.poll() is not None:
                raise LogisimMcpError(
                    f"Logisim Evolution exited during startup with code {process.returncode}"
                )
            return {
                "opened": True,
                "mode": "launched_without_live_plugin",
                "path": relative,
                "process_id": process.pid,
                "note": "Live plugin JAR not found; later opens will start another window.",
            }

        deadline = time.monotonic() + max(5.0, wait_seconds)
        status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LogisimMcpError(
                    f"Logisim Evolution exited during startup with code {process.returncode}"
                )
            status = self.live.ping(timeout=2.0)
            if status and self._project_listed(status, resolved):
                return {
                    "opened": True,
                    "mode": "launched_app",
                    "path": relative,
                    "process_id": process.pid,
                    "live_control": True,
                    "archived_autosaves": status.get("archived_autosaves_at_startup", []),
                }
            time.sleep(0.4)
        return {
            "opened": True,
            "mode": "launched_app",
            "path": relative,
            "process_id": process.pid,
            "live_control": status is not None,
            "warning": (
                "Logisim started but did not report the project as loaded within "
                f"{wait_seconds:.0f} s; a dialog may be waiting in the Logisim window."
            ),
        }

    @staticmethod
    def _project_listed(status: dict[str, Any], resolved: Path) -> bool:
        target = os.path.normcase(str(resolved))
        for entry in status.get("projects") or []:
            path = entry.get("path")
            if path and os.path.normcase(str(Path(path).resolve())) == target:
                return True
        return False

    def probe(self, timeout_seconds: int = 15) -> dict[str, Any]:
        if self.executable is None:
            return {"configured": False, "available": False, "message": "LOGISIM_EVOLUTION is not set"}
        if not self.executable.exists():
            return {
                "configured": True,
                "available": False,
                "executable": str(self.executable),
                "message": "Configured Logisim file does not exist",
            }
        command = (
            [self.java_executable, "-jar", str(self.executable), "--version"]
            if self.executable.suffix.lower() == ".jar"
            else [str(self.executable), "--version"]
        )
        try:
            completed = subprocess.run(
                command,
                cwd=self.policy.root,
                capture_output=True,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                timeout=max(1, min(timeout_seconds, 60)),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "configured": True,
                "available": False,
                "executable": str(self.executable),
                "message": str(exc),
            }
        stdout, stdout_suppressed = self._clean_output(completed.stdout)
        stderr, stderr_suppressed = self._clean_output(completed.stderr)
        return {
            "configured": True,
            "available": completed.returncode == 0,
            "executable": str(self.executable),
            "exit_code": completed.returncode,
            "version": stdout.strip(),
            "stderr": stderr,
            "suppressed_line_count": stdout_suppressed + stderr_suppressed,
        }

    def run_test_vector(
        self,
        project_path: Path,
        circuit_name: str,
        vector_file: str | Path,
        *,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        vector_path = self.policy.resolve(vector_file, suffixes=(".txt", ".vec", ".test"))
        command = self.build_command(circuit_name, vector_path, project_path)
        try:
            completed = subprocess.run(
                command,
                cwd=self.policy.root,
                capture_output=True,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                timeout=max(1, min(timeout_seconds, 1800)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LogisimMcpError(
                f"Logisim test timed out after {timeout_seconds} seconds"
            ) from exc
        stdout, stdout_suppressed = self._clean_output(completed.stdout)
        stderr, stderr_suppressed = self._clean_output(completed.stderr)
        return {
            "passed": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "suppressed_line_count": stdout_suppressed + stderr_suppressed,
            "command": [
                "java" if i == self.java_executable else i for i in command
            ],
        }

    @staticmethod
    def _clean_output(value: str, limit: int = 20_000) -> tuple[str, int]:
        """Bound process output and fold noisy Windows Java preference warnings."""
        noisy_fragments = (
            "java.util.prefs.WindowsPreferences",
            "Could not open/create prefs root node",
            "Trying to recreate Windows registry node",
            "Could not open windows registry node",
        )
        kept: list[str] = []
        suppressed = 0
        for line in value.splitlines(keepends=True):
            if any(fragment in line for fragment in noisy_fragments):
                suppressed += 1
            else:
                kept.append(line)
        text = "".join(kept)
        if len(text) > limit:
            text = f"[...output truncated to last {limit} characters...]\n" + text[-limit:]
        if suppressed:
            text += f"[suppressed {suppressed} repetitive Java preferences warning lines]\n"
        return text, suppressed
