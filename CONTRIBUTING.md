# Contributing

Thanks for helping! Issues and pull requests are welcome.

- Set up and run the tests as described in [docs/development.md](docs/development.md).
- Keep tools focused and safe: the server must never gain arbitrary file access, and new
  edit paths must go through `ProjectService.edit()` so they stay live and undoable.
- Base Logisim behaviour on its source (Logisim Evolution 5.0.0) and note the classes you
  relied on in [docs/logisim-source-notes.md](docs/logisim-source-notes.md).
- If you change `java-plugin/`, rebuild the plugin JAR and add or update a GUI test.
- Describe user-visible changes in `CHANGELOG.md`.

By contributing you agree that your contributions are licensed under the project's
licenses (MIT for the Python bridge, GPL-3.0-or-later for `java-plugin/`).
