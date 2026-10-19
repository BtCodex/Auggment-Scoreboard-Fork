# Android / Fire TV / Shield viewer

This is a **server-connected Android viewer**, not a standalone sports-data server.
The APK opens the existing Flask scoreboard in a fullscreen Android WebView. Your
Raspberry Pi (or another scoreboard server) must remain running and reachable on
the same network. Installing the APK does not install, upgrade, or change anything
on the Pi. Its sports data, favorite teams, logos, colors, timezone, and display
modes all come from the existing server.

## What is implemented

- Native Java app without Gradle/runtime frameworks, Google Play Services, ads,
  analytics, native ARM libraries, or a bundled Python server.
- Server URL saved in private app preferences; touchscreen and D-pad-friendly setup.
- Phone/tablet launcher and Android TV/Fire TV launcher entries and banner.
- Fullscreen display while the app is open; keeps the display awake.
- First-load/server-startup recovery with 2, 4, 8, 16, 32, then 60-second retry
  delays, five-second network probe timeouts, and a 20-second page-load timeout.
  Only one retry probe runs at a time. No repeated native polling after the page loads.
- Once loaded, the existing scoreboard handles sports-data outages and retains
  its previous cards. The viewer does not repeatedly reload a working page during
  an outage. Reopening the app requests a data refresh without replacing the page.
- On Android 8+ a stopped WebView renderer is removed and the viewer is recreated
  after 30 seconds while visible. This recovery path still needs device testing.
- Back, remote Menu, long press, or the small **⋮** button opens maintenance controls.
  Choose **Exit viewer** to leave fullscreen or **Change server address** to reconnect.
- Optional launch notification after reboot on devices supporting notifications.
  Notification permission is requested on Android 13+. This is not automatic app launch.
- HTTP is allowed because the existing LAN server uses HTTP. Native URL validation
  rejects non-HTTP schemes and embedded credentials; main-page navigation is kept
  on the configured server origin. WebView file/content access, third-party cookies,
  JavaScript-to-native bridges, and remote debugging are disabled. HTTPS certificate
  errors are not bypassed. Use this on a trusted LAN; do not expose Flask to the internet.

## Device compatibility and startup limits

The APK declares Android 5.1/API 22 minimum, target API 35, and no required
touchscreen. It contains no architecture-specific native code, so its own code
can run on ARM32, ARM64, and x86 Android devices. **The scoreboard page additionally
requires a modern JavaScript/WebView implementation**; declaring an older Android
minimum does not make an obsolete WebView compatible. Update Android System
WebView or the device's Fire OS before testing. Very old Fire TV models may be
unable to update their WebView enough to display this application.

- **Android phone/tablet:** use an up-to-date Android System WebView. Optional
  boot notification depends on notification permission and vendor power policies.
- **NVIDIA Shield / Android TV:** the leanback launcher entry supports opening the
  app with a remote. Test D-pad focus, overscan, sleep/wake, and WebView availability.
- **Amazon Fire TV / Fire TV Stick running Android-based Fire OS:** sideloading may
  work without Google services. Test the actual device's WebView and remote;
  installation alone does not verify rendering or boot behavior.
- **Fire TV models running Vega OS rather than Android/Fire OS:** Android APKs
  cannot be installed. Use a supported browser if available or a different device.

Modern Android restricts starting activities in the background after boot. The
app deliberately does not attempt to bypass those restrictions. For unattended
startup, use a kiosk/device-owner launcher appropriate to the exact device and
configure it to launch this app; Fire TV may further restrict launcher replacement.
That setup and physical reboot testing are not included or verified here. The
optional boot notification offers a manual launch on supported Android devices
after the app has been opened at least once.

## Build a test APK (Linux/macOS)

This build needs a full JDK 17 or newer, the Android SDK command-line tools, and
the `zip` command. It does not add dependencies to the Raspberry Pi application.
Install the tools on your development computer, not on your Pi. Google's tools
and SDK have their own licenses; review and accept them through `sdkmanager`.

```bash
export ANDROID_SDK_ROOT=/path/to/your/android-sdk
export JAVA_HOME=/path/to/your/jdk
"$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" \
  'platforms;android-35' 'build-tools;35.0.0'
bash android/test.sh
bash android/build.sh
```

Output: `android/dist/auggmented-scoreboard-viewer-debug.apk`.
The build compiles Java, packages resources, converts bytecode with D8, aligns the
APK, signs it with a local debug key, and verifies the signature and alignment.
The ignored key lives in `android/.build/debug.keystore`; no key is committed.
Keep that key locally to install later debug builds over an earlier installation.
A build from another machine/CI uses a different key; uninstall the old test app
before installing that build, which also removes its saved server address.

The GitHub Actions workflow **Android server-connected viewer** runs the same
tests/build and uploads a 30-day downloadable APK artifact. A workflow definition
in the branch does not mean a remote CI build has already passed: check its run
status before downloading. Production/app-store distribution and release signing
are separate from this sideloadable debug build. The source is GPLv3-or-later;
provide corresponding source and the repository's `LICENSE` when redistributing.

## Sideload and connect

An actual compiled test build is included at
[`android/artifacts/auggmented-scoreboard-viewer-debug.apk`](../android/artifacts/auggmented-scoreboard-viewer-debug.apk),
alongside its SHA-256 checksum. It matches the local build report. This binary is
provided for sideload testing; no Android hardware or emulator test is claimed.

1. Keep your current scoreboard/Pi installation as it is. Confirm the display
   opens in a browser on the same Wi-Fi: `http://<Pi-IP>:5000/` (or your configured port).
2. Download the APK to the Android device. Enable installation from the specific
   downloader/file manager temporarily, install it, then disable that permission.
   On Fire TV, sideloading/developer menus depend on the model and Fire OS version.
   Alternatively, from a trusted development computer with Android platform tools:
   `adb install android/artifacts/auggmented-scoreboard-viewer-debug.apk`.
3. Open **Auggmented Scoreboard**, enter the same display URL, and select
   **Save and open scoreboard**. A Pi address is needed; `localhost` would refer
   to the Android device itself. Guest Wi-Fi/client isolation can block LAN access.
4. Manage scoreboard settings from your phone at `http://<Pi-IP>:5000/settings`.
   Those remain the server's shared settings, not a separate Android display profile.
5. To remove the viewer, uninstall it in Android settings. This leaves the Pi,
   server settings, uploaded logo, and favorite teams untouched.

Do not enable internet-facing port forwarding or disable certificate validation
to connect. Self-signed HTTPS requires a trusted certificate/device setup; the
viewer intentionally does not accept invalid certificates.

## What was and was not tested

See `android/BUILD_REPORT.md` for the actual local compiler, APK signature,
manifest, policy-test results, size, and checksum. These checks establish that the
artifact builds and is structurally valid; they do not establish device runtime
compatibility. No phone, Fire TV, Shield, emulator, boot launcher, or long-running
Android memory test has been run in the cloud environment.

Before relying on the viewer, test on each intended model:

1. Fresh install, correct/incorrect server URL, saving and reopening after force stop.
2. D-pad or touchscreen navigation, Back/menu exit, portrait/landscape, TV overscan.
3. All display modes; clock/header settings, logos, rankings, and detailed scorecards.
4. Start the app while the server is stopped, then start the server and confirm recovery.
5. Drop Wi-Fi and stop the server after cards have loaded; confirm retained scores
   are marked stale and new scores resume when connectivity returns.
6. Reboot, sleep/wake, any chosen kiosk launcher, and the optional boot notification.
7. Run for 24–48 hours and inspect device memory/heat. APK size is not a measurement
   of WebView RAM; actual device measurements are still required.

## Fully standalone Android feasibility

Not implemented. A WebView shell cannot execute Flask/Python by itself. A genuine
standalone version would need to bundle Python plus the existing backend and its
dependencies for the relevant ARM ABIs (for example with a maintained Android
Python embedding toolchain), or port the providers, caching, settings, and score
processing to Android. It would also need an on-device service lifecycle, local
server or native rendering, scoped storage migration, provider-network testing,
background/foreground service handling, security review, and separate 24/7 device
tests. Each standalone display would make its own provider requests unless a
shared data service remained. The current server-connected APK is the smaller,
simpler approach and shares the Pi's existing cache and rate limits.
