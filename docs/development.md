# Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                                            # unit tests (no Java needed)
```

## Real Logisim tests

The GUI tests start Logisim with the live plugin, edit circuits, simulate, and save.
They need Java 21+, the official JAR and a display (Xvfb on headless Linux):

```bash
curl -fL -o tools/logisim-evolution-5.0.0-all.jar \
  https://github.com/logisim-evolution/logisim-evolution/releases/download/v5.0.0/logisim-evolution-5.0.0-all.jar
export LOGISIM_EVOLUTION=$PWD/tools/logisim-evolution-5.0.0-all.jar
xvfb-run -a pytest        # or set DISPLAY yourself
```

## The Java plugin

Source: `java-plugin/src/vn/logisimmcp/live/`. The prebuilt JAR used at runtime is
`src/logisim_mcp/plugin/logisim-mcp-live-plugin.jar`; rebuild it after changing the Java code:

```bash
java-plugin/build-plugin.sh tools/logisim-evolution-5.0.0-all.jar     # or build-plugin.ps1
```

CI compiles the plugin against the official Logisim JAR (API compatibility check) and runs
the GUI tests with the committed JAR, so always commit the rebuilt JAR with the source.

## Docs

`docs/tools.md` is generated: `python scripts/dev/gen_tool_docs.py`.

## Releasing

1. Update `version` in `pyproject.toml`, `src/logisim_mcp/__init__.py` and
   `java-plugin/MANIFEST.MF`; add a `CHANGELOG.md` entry.
2. Rebuild the plugin and regenerate `docs/tools.md`.
3. `python -m build` and tag `vX.Y.Z`; the release workflow attaches the wheel and sdist.
