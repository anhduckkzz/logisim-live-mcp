#!/usr/bin/env bash
# Rebuilds src/logisim_mcp/plugin/logisim-mcp-live-plugin.jar (needs JDK 21+).
# Usage: java-plugin/build-plugin.sh [path/to/logisim-evolution-5.0.0-all.jar]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
jar_path="${1:-$here/../tools/logisim-evolution-5.0.0-all.jar}"
build="$here/build"
rm -rf "$build" && mkdir -p "$build/classes"
javac --release 21 -Xlint:unchecked -cp "$jar_path" -d "$build/classes" "$here"/src/vn/logisimmcp/live/*.java
out="$here/../src/logisim_mcp/plugin/logisim-mcp-live-plugin.jar"
jar cfm "$out" "$here/MANIFEST.MF" -C "$build/classes" .
echo "Built $out"
