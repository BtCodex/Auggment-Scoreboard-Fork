"""Build the flat, runtime-only update ZIP without device data or startup files.

Run from any directory: python scripts/build_update_package.py
The output is deterministic for identical source files and version.txt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    'app.py', 'score_details.py', 'cfb_week.py', 'version.txt', 'requirements.txt', 'LICENSE',
    'templates/index.html', 'templates/settings.html', 'templates/login.html',
    'static/css/main.css', 'static/css/display-modes.css', 'static/css/live-widgets.css',
    'static/js/clock.js', 'static/js/display.js', 'static/js/live-widgets.js',
    'static/data/football-teams-2026.json', 'scripts/network_helper.py',
)
ARTIFACT_BASE = ('https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/'
                 'improve/complete-weekly-cfb-rotation/artifacts/')


def build(output_directory=None):
    output_directory = Path(output_directory) if output_directory else ROOT / 'artifacts'
    version = (ROOT / 'version.txt').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', version):
        raise ValueError('Unsafe or missing application version')
    for relative in RUNTIME_FILES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or symlinked runtime file: ' + relative)
    output_directory.mkdir(parents=True, exist_ok=True)
    package = output_directory / ('scoreboard-update-' + version + '.zip')
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in RUNTIME_FILES:
            info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / relative).read_bytes(), compresslevel=9)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    (output_directory / 'SHA256SUMS').write_text(digest + '  ' + package.name + '\n', encoding='utf-8')
    manifest = {'version': version, 'download_url': ARTIFACT_BASE + package.name,
                'sha256': digest, 'package_type': 'runtime-only',
                'instructions_url': ('https://github.com/BtCodex/Auggment-Scoreboard-Fork/blob/'
                                     'improve/complete-weekly-cfb-rotation/docs/UPDATE_PACKAGE.md')}
    (output_directory / 'update-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return package, digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    arguments = parser.parse_args()
    package_path, checksum = build(arguments.output_dir)
    print(str(package_path))
    print('SHA-256: ' + checksum)
