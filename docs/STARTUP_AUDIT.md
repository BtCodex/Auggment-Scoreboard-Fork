# Startup audit and physical verification

The development environment did not access a Raspberry Pi or install services.
`install.sh` remains a fresh/test-installation tool: it installs packages and
configures LightDM/Openbox. Use the migration guide for an existing installation,
preferably on a cloned SD card. Never run the full installer as a routine update.

## Confirmed problems corrected

- The old launcher waited at most 60 attempts, then opened Chromium even if the
  backend was unavailable. It now waits for a working local HTTP response, with
  bounded connection/request timeouts and periodic diagnostic messages. It also
  waits for the actual X11 session, rather than assuming autologin has completed.
- Ordering the kiosk after `graphical.target` while enabling it under that target
  can create an ordering cycle. The unit now starts after the display manager and
  backend, and the launcher handles actual readiness.
- Fresh Pi OS Lite installations normally boot to `multi-user.target`. The fresh
  kiosk/combined installer now explicitly enables graphical boot and saves the
  previous default target for rollback. Systemd resolves the distribution's
  LightDM unit path; the installer no longer creates a possibly broken `/lib`
  display-manager symlink.
- Backend and browser failures retry at 10-second and 15-second intervals,
  respectively. There is no permanent start-limit lockout after a long outage.
  `systemctl stop` still stops a service without triggering its restart policy.
- The backend no longer depends on `network-online.target`. Local/cached data
  can appear while internet connectivity is unavailable.
- Installed and manual kiosks now use one maintained launcher copied unchanged.
  Its port follows validated settings (1–65535); legacy kiosk mode remains
  supported. Explicit IPv4 loopback avoids localhost/IPv6 ambiguity.
- Server/Combined installation no longer creates a kiosk mode marker by copying
  a staged `kiosk.json`. Missing mode/port keys are initialized explicitly and
  atomically; existing explicit settings remain unchanged, even on reinstall.
- Fresh installs copy all shipped CSS and JavaScript, including display modes,
  and retain the GPL license. Required files are checked before installation.
- Existing custom logos, uploads, favorites, colors, pairing information,
  `.session-key`, and score snapshots are preserved. Existing app directories and
  service units receive backups before replacement. Sensitive JSON files and
  session keys use mode 600; uploaded media is not made executable/readable to
  every local account by a recursive chmod.
- Regular desktop users run Chromium with its sandbox enabled. The launcher no
  longer terminates unrelated browsers or starts duplicate cursor-hide daemons.
  Actual account home/primary group information is honored. Missing `render`
  groups on older systems do not abort installation.
- The installer no longer purges Apache, installs a replacement network manager,
  injects a potentially conflicting `192.168.1.250` address, overrides managed
  system Python with pip, or reboots automatically.
- Unrestricted root access to network utilities is replaced by a root-owned
  `/usr/local/libexec/scoreboard-network` helper. It permits only supported Wi-Fi
  argument structures and real wireless interfaces, resolves absolute distro
  binaries, and never runs a shell. The writable source copy in `scripts/` is
  never sudo-authorized. Service-control grants name exact actions and units.
  Sudoers content is validated before replacement.

## Checks actually run

- `python -m unittest discover -s tests -p test_startup_improvements.py -v`:
  **19 tests passed**. These exercise generated units, all three fresh-mode
  initializations, backward-compatible settings preservation, corrupt-config
  refusal, mocked browser launches, late backend readiness beyond 60 attempts,
  late X11, malformed ports/geometry, and privileged helper allow/deny rules.
- Existing startup tests were updated to inspect generated units and run mocked
  launchers. Bash syntax checks cover each of the three scripts individually.
- Generated backend and kiosk units passed `systemd-analyze verify --man=no`
  with exit status 0. The validator initially found an invalid quoted
  `WorkingDirectory` directive; it was corrected and validation rerun.
- Host commands in launcher tests are mocks. Full package installation, actual
  systemd enablement/start/stop, LightDM autologin, Wi-Fi changes, and Chromium on
  Raspberry Pi hardware have **not** been run.

## Maintenance and recovery on the test Pi

Open a second terminal with **Ctrl+Alt+F2**, log in, then run:

```sh
sudo systemctl stop kiosk.service
```

The browser closes and stays stopped for maintenance. Resume with:

```sh
sudo systemctl start kiosk.service
```

Use these read-only diagnostics when a display fails:

```sh
systemctl status scoreboard.service kiosk.service lightdm.service
journalctl -u scoreboard.service -u kiosk.service -u lightdm.service -b --no-pager
systemctl get-default
```

The web settings also provide kiosk stop/start controls when installed. Merely
closing Chromium can cause it to reopen under its restart policy.

## Required physical checks

On a cloned/spare SD card, test Server, Kiosk, or Combined as appropriate for the
actual installation. Verify cold boot, delayed backend, backend/browser crash
recovery, boot with no internet, Wi-Fi loss and return, HDMI orientation and
resolution, display power scheduling, and 24–48 hours of operation. Check memory,
CPU, temperature and undervoltage flags throughout the run.

Pi OS 32-bit (`armv7l`/armhf) and 64-bit (`aarch64`/arm64) use distro Chromium
packages; no x86 Chrome binary is selected on ARM. This is architecture selection
verified in code, not a claim of installation on either Pi userland. The fresh
installer configures **X11/Openbox**. An existing Wayland desktop needs a separate
review of its session/display authorization; do not overwrite it using this
installer. Dual-monitor independent kiosk placement is not implemented here.

No router port forwarding or public internet exposure is configured. The backend
is reachable on the home LAN; use a trusted LAN and change default credentials.
