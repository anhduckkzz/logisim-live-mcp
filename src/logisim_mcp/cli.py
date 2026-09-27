from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .errors import LogisimMcpError
from .runner import LogisimRunner
from .server import create_server
from .service import ProjectService


def _print(value: Any) -> None:
    # ASCII-safe JSON also works in the legacy Windows console code pages that
    # cannot encode every character Logisim may emit on stdout/stderr.
    print(json.dumps(value, indent=2, ensure_ascii=True, default=str))


def _service(args: argparse.Namespace) -> ProjectService:
    service = ProjectService(args.root)
    if getattr(args, "project", None):
        service.open_project(args.project)
    return service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logisim-mcp", description="Logisim Live MCP: live MCP server for Logisim Evolution, plus a local debugging CLI"
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("LOGISIM_PROJECT_ROOT", "."),
        help="Only files beneath this directory may be accessed",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = sub.add_parser("inspect", help="Inspect a project or one circuit as JSON")
    inspect_cmd.add_argument("project")
    inspect_cmd.add_argument("--circuit")

    create_cmd = sub.add_parser("create", help="Create a native Logisim Evolution 5.0.0 project")
    create_cmd.add_argument("project")
    create_cmd.add_argument("--main", default="main")
    create_cmd.add_argument("--overwrite", action="store_true")

    validate_cmd = sub.add_parser("validate", help="Validate a project")
    validate_cmd.add_argument("project")

    backups_cmd = sub.add_parser("backups", help="List backups for a project")
    backups_cmd.add_argument("project")

    backup_cmd = sub.add_parser("backup", help="Create a manual backup")
    backup_cmd.add_argument("project")
    backup_cmd.add_argument("--reason", default="manual-cli")

    rollback_cmd = sub.add_parser("rollback", help="Rollback to a bridge-created backup")
    rollback_cmd.add_argument("project")
    rollback_cmd.add_argument("backup_path")

    doctor_cmd = sub.add_parser("doctor", help="Check bridge and Logisim configuration")
    doctor_cmd.add_argument("--logisim", default=os.environ.get("LOGISIM_EVOLUTION"))

    test_cmd = sub.add_parser("test", help="Run a Logisim Evolution test vector")
    test_cmd.add_argument("project")
    test_cmd.add_argument("circuit")
    test_cmd.add_argument("vector_file")
    test_cmd.add_argument("--logisim", default=os.environ.get("LOGISIM_EVOLUTION"))
    test_cmd.add_argument("--timeout", type=int, default=120)

    open_cmd = sub.add_parser("open", help="Open a saved project in native Logisim Evolution")
    open_cmd.add_argument("project")
    open_cmd.add_argument("--logisim", default=os.environ.get("LOGISIM_EVOLUTION"))
    open_cmd.add_argument(
        "--force-reload",
        action="store_true",
        help="Discard unsaved edits made by hand in the running Logisim window",
    )

    live_cmd = sub.add_parser("live-status", help="Show whether a live Logisim window is reachable")
    live_cmd.add_argument("--logisim", default=os.environ.get("LOGISIM_EVOLUTION"))

    serve_cmd = sub.add_parser("serve", help="Start the MCP server")
    serve_cmd.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    serve_cmd.add_argument("--logisim", default=os.environ.get("LOGISIM_EVOLUTION"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            server = create_server(
                args.root, logisim_executable=args.logisim, host=args.host, port=args.port
            )
            server.run(transport=args.transport)
            return 0

        if args.command == "doctor":
            service = ProjectService(args.root)
            _print(
                {
                    "allowed_root": str(service.policy.root),
                    "logisim": LogisimRunner(service.policy, args.logisim).probe(),
                }
            )
            return 0

        if args.command == "live-status":
            service = ProjectService(args.root)
            _print(LogisimRunner(service.policy, args.logisim).live_status())
            return 0

        if args.command == "create":
            service = ProjectService(args.root)
            _print(
                service.create_project(
                    args.project, main_circuit=args.main, overwrite=args.overwrite
                )
            )
            return 0

        service = _service(args)
        if args.command == "inspect":
            project = service.require_project()
            _print(project.read_circuit(args.circuit) if args.circuit else project.summary())
        elif args.command == "validate":
            result = service.validate()
            _print(result)
            return 0 if result["valid"] else 2
        elif args.command == "backups":
            _print(service.list_backups())
        elif args.command == "backup":
            _print(service.create_backup(args.reason))
        elif args.command == "rollback":
            _print(service.rollback(args.backup_path))
        elif args.command == "test":
            project = service.require_project()
            runner = LogisimRunner(service.policy, args.logisim)
            result = runner.run_test_vector(
                project.path, args.circuit, args.vector_file, timeout_seconds=args.timeout
            )
            _print(result)
            return 0 if result["passed"] else 1
        elif args.command == "open":
            project = service.require_project()
            if project.dirty:
                service.save()
            _print(
                LogisimRunner(service.policy, args.logisim).open_project(
                    project.path, force_reload=args.force_reload
                )
            )
        return 0
    except (LogisimMcpError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
