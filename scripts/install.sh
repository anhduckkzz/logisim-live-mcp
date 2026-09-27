#!/usr/bin/env bash
# Linux/macOS setup: venv, bridge, official Logisim Evolution 5.0.0 JAR (checksum verified),
# doctor check, and ready-to-paste client configs in generated-config/.
# Usage: scripts/install.sh ~/LogisimProjects
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
project_root="$(mkdir -p "${1:?usage: scripts/install.sh <project-root>}" && cd "$1" && pwd)"
jar="$root/tools/logisim-evolution-5.0.0-all.jar"
url="https://github.com/logisim-evolution/logisim-evolution/releases/download/v5.0.0/logisim-evolution-5.0.0-all.jar"
sha="6b368e894742c04cc83aa9830f869bcab0190ede4df43ad6fecdb89b3a23a41c"

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11+ required"; exit 1; }
[ -x "$root/.venv/bin/python" ] || python3 -m venv "$root/.venv"
"$root/.venv/bin/python" -m pip install --upgrade pip
"$root/.venv/bin/python" -m pip install -e "$root[dev]"

mkdir -p "$root/tools"
[ -f "$jar" ] || curl -fL "$url" -o "$jar"
actual="$( (sha256sum "$jar" 2>/dev/null || shasum -a 256 "$jar") | cut -d' ' -f1)"
[ "$actual" = "$sha" ] || { echo "Logisim JAR checksum mismatch: $actual"; exit 1; }

"$root/.venv/bin/python" -m logisim_mcp --root "$project_root" doctor --logisim "$jar"

mkdir -p "$root/generated-config"
cat > "$root/generated-config/claude_desktop_config.json" <<JSON
{
  "mcpServers": {
    "logisim": {
      "command": "$root/.venv/bin/python",
      "args": ["-m", "logisim_mcp", "--root", "$project_root", "serve", "--transport", "stdio", "--logisim", "$jar"]
    }
  }
}
JSON
cat > "$root/generated-config/codex-config.toml" <<TOML
[mcp_servers.logisim]
command = "$root/.venv/bin/python"
args = ["-m", "logisim_mcp", "--root", "$project_root", "serve", "--transport", "stdio", "--logisim", "$jar"]
startup_timeout_sec = 30
tool_timeout_sec = 300
TOML
echo "Done. Client configs are in $root/generated-config/"
