# Runtime-only Raspberry Pi update artifact

- [Download the ZIP](scoreboard-update-1.5.0-dev.zip)
- [SHA-256 checksum](SHA256SUMS)
- [Existing update-source manifest](update-manifest.json)
- [Compatibility and installation choices](../docs/UPDATE_PACKAGE.md)

Use the manual ZIP procedure for an unknown/intermediate installed updater.
The package excludes settings, uploads and kiosk/startup configuration. It is
not a fresh OS installer; use the Git installation guide on a fresh test card.

Rebuild with `python scripts/build_update_package.py`; reproducible ZIP and
installed-runtime preservation tests are in `tests/test_update_distribution.py`.
