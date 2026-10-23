# Choose the ZIP update or a clean Git installation

Try the [existing-install ZIP procedure](ZIP_UPDATE.md) first. It backs up the
whole application and copies only runtime files, without reinstalling Raspberry
Pi OS, requiring Git, or changing kiosk startup. A [fresh 32-bit Pi OS Git
installation](FRESH_PI_INSTALL.md) remains the backup option; it runs directly
from its checkout for later `git pull --ff-only` updates.

The actual update artifact is
[`artifacts/scoreboard-update-1.5.0-dev.zip`](../artifacts/scoreboard-update-1.5.0-dev.zip).
[`SHA256SUMS`](../artifacts/SHA256SUMS) identifies its exact bytes. The flat ZIP
contains app.py, both required Python modules, version/unchanged requirements,
license, templates, CSS/JS, the football catalog and network-helper **source**.
It omits settings, credentials, cache, uploads, `.git`, install.sh, kiosk launchers,
systemd units, desktop files and privileged helper installations.

No runtime dependency was added. Keep the existing interpreter/dependency method;
the manual guide checks Flask, Requests, pytz and python-dateutil before stopping
services. A source CSS/template file you manually edited cannot be automatically
merged; the full backup retains it, while saved theme/color choices remain in
settings.json.

## What updater compatibility was actually tested

| Installed updater | Result / update route |
| --- | --- |
| Original upstream 1.3, commit `d6d3a4a995c31480c748809b6ec7f13b3690b67e` | The exact extraction function was executed against this real package in an isolated fixture. All runtime files installed; existing configuration, uploads and kiosk scripts remained unchanged. The installed Flask application then imported and served API/page smoke checks. |
| Updated updater in this branch | The actual updater installed the same package, retained code backups, preserved device/startup data, and passed the same installed-runtime smoke checks. It accepts both new Python modules and rejects app.py packages that omit an imported required module before writing files. |
| Intermediate fork or another modified updater | **Not universally compatible.** Some filtered allowlists omit new root modules/catalog assets, potentially leaving an app that cannot start. Use the manual procedure once to install the complete runtime and upgraded updater. |

Original upstream 1.3 extracts new modules. Filtered intermediate updaters and
unknown modifications can behave differently. Because your exact installed code
cannot be inspected remotely here, the manual route is the recommended first
update. A version number alone does not identify a locally modified updater.

These tests exercise application files in temporary directories on cloud x86_64,
not Pi hardware, network downloads from your Pi, rebooting, or the whole legacy
web Apply/reboot flow. No Raspberry Pi was contacted or changed.

## Optional existing web update mechanism

The application discovers a ZIP by its update-source JSON URL; it does not offer
a local ZIP upload control. If your updater is a known compatible implementation,
first make the full private backup in [the manual guide](ZIP_UPDATE.md). If you
used its stop-and-backup step, restart the original backend and previously active
kiosk before opening web settings. Then set **Software Updates → Update Source
URL** to:

```text
https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/improve/complete-weekly-cfb-rotation/artifacts/update-manifest.json
```

Save, select **Check for Updates**, verify `1.5.0-dev` and the fork's ZIP, and only
then choose Apply. The exact original and current version-check functions were
tested against the manifest shape. The original upstream Apply flow may reboot
the Pi automatically; schedule that interruption. The new package itself does
not modify boot configuration or service units.

The updated application deliberately refuses the default original-upstream update
source, which could overwrite the fork. A Git checkout also refuses web ZIP Apply:
use the documented Git update procedure there. Do not enable automatic application
of an unreviewed development update.

The manifest's SHA-256 is provided for manual verification; **the old update
client does not automatically enforce that manifest field**. HTTPS certificate
verification stays enabled. Direct download for the manual route:

```bash
mkdir -p "$HOME/scoreboard-download"
cd "$HOME/scoreboard-download"
curl --fail --location --retry 3 \
  'https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/improve/complete-weekly-cfb-rotation/artifacts/scoreboard-update-1.5.0-dev.zip' \
  --output scoreboard-update-1.5.0-dev.zip
curl --fail --location --retry 3 \
  'https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/improve/complete-weekly-cfb-rotation/artifacts/SHA256SUMS' \
  --output SHA256SUMS
sha256sum --check SHA256SUMS
```

Continue through the manual guide only after checksum verification succeeds.
Do not extract directly over the running application or copy a whole downloaded
source tree over private device files.

## Rollback and validation

Use [the ZIP rollback procedure](ZIP_UPDATE.md#rollback-without-reinstalling-the-os)
or [the Git installation rollback](FRESH_PI_INSTALL.md#roll-back-a-failed-update).
Restore **settings and code together**, because password/conference representations
can migrate after a save/login. Restart the backend first, check the configured
port and service logs, and then restart the previously active kiosk.

Verify saved teams/themes, actual artwork, complete CFB ordering, the Live /
Upcoming / Both filter, optional finals and unchanged ticker. Physical boot,
actual October 24 ESPN schedule comparison and a 24–48 hour Pi soak remain required.

## Reproduce the package

From the reviewed source checkout (development computer only):

```bash
python scripts/build_update_package.py
python -m unittest discover -s tests -p test_update_distribution.py -v
```

The builder has an explicit runtime allowlist and fixed ZIP timestamps/modes.
Identical inputs and Python/zlib toolchain produce identical bytes. A regression test rejects a published
artifact that no longer matches its runtime sources, so rebuild the ZIP and
checksum whenever packaged code changes.
