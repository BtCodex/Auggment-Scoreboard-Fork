# Sideload test build

`auggmented-scoreboard-viewer-debug.apk` is the actual locally compiled and
signature-verified server-connected Android viewer. Its corresponding source is
in `android/src`, with build instructions in `docs/ANDROID_VIEWER.md` and the
repository's GPLv3 license bundled as `assets/LICENSE` inside the APK.

This artifact uses a private, ignored local debug key. No signing key is included
in Git or the APK. It is a physical-test candidate, not a device-tested release.
Phones/tablets, Android-based Fire TV and Shield still require hardware tests;
Vega OS cannot run Android APKs. A running Flask scoreboard server is required.

From the checkout root, verify the committed binary:

```bash
sha256sum -c android/artifacts/SHA256SUMS
```

Size: 37,477 bytes. SHA-256:
`e6c5dbbdc4fed3123211b133a54d71a2a88bafa11c9bec031c0c4fe3e3aab0fc`.

Rebuilding with `android/build.sh` writes to ignored `android/dist/`. Different
signing keys or builds produce a different checksum. Keep the matching debug key
locally for later in-place updates; otherwise uninstall the earlier test app
before installing a differently signed build, which clears only the viewer's
saved address. It does not change your Pi or server settings.
