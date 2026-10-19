# Android debug APK build report

Local cloud build completed on 2026-10-19. This is a **server-connected viewer**,
not a standalone scoreboard and not a device-tested release.

| Check | Actual result |
|---|---|
| Java compiler | Temurin OpenJDK 21.0.10+7, Java 8 bytecode target |
| Android platform | Android 35, platform revision 2 |
| Android build tools | 35.0.0 |
| `bash android/test.sh` | **28 URL/origin/reconnect-policy checks passed**, zero failed |
| `bash -n android/build.sh android/test.sh` | Passed |
| Full APK Java/resource/D8 compilation | Passed |
| `apksigner verify --verbose` | Passed; v1, v2, and v3 signatures verified |
| `zipalign -c -p 4` | Passed |
| Packaged manifest inspection | Package `org.auggmented.scoreboard.viewer`; version `0.1.0` / code `1`; min API 22; target API 35; standard and leanback launcher entries; touchscreen/leanback optional |
| APK contents | `classes.dex`, resources, manifest, and exact repository `assets/LICENSE` present; no native libraries, Python files, settings JSON, or signing key included |
| APK size | **37,477 bytes** (about 36.6 KiB); this is not a RAM measurement |

Built artifact: `android/dist/auggmented-scoreboard-viewer-debug.apk`.
An identical copy is committed in `android/artifacts/` for direct download, with
`SHA256SUMS`; the build output and private signing key remain ignored.

SHA-256:

```text
e6c5dbbdc4fed3123211b133a54d71a2a88bafa11c9bec031c0c4fe3e3aab0fc
```

The build uses a local ignored debug signing key. Another machine/CI produces a
different signature and checksum; retain the local key for in-place test updates
or uninstall the old test app before installing a differently signed build.
Compiler warnings concern intentional legacy Android API fallbacks and the Java 8
bytecode target; no compiler errors remain. Optional APK signature v3.1/v4 and
SourceStamp are not present and are not required for this debug sideload build.

The official platform/build-tools archive SHA-1 checksums matched Google's SDK
repository manifest. `sdkmanager` could not fetch its package lists through the
cloud network, so this local build used the official archives directly. Normal
developer and CI instructions use `sdkmanager`.

An independent read-only review found and prompted fixes for stale WebView
callbacks, removed-renderer null safety, setup cancellation, initial-load guards,
and HEAD-disabled proxy recovery. All source was recompiled after those fixes.

**Not run:** Android emulator, phone/tablet, Fire TV, Shield, native UI interaction,
notification/boot launcher, real-network reconnect, renderer-crash recovery, or
extended Android RAM/thermal tests. The GitHub Actions workflow is supplied, but
its remote execution status must be checked separately. No Raspberry Pi was
accessed, changed, or deployed to.

See [Android viewer instructions](../docs/ANDROID_VIEWER.md) for installation,
limitations, and the required physical-device checklist.
