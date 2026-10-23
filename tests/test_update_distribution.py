"""Exercise the real runtime ZIP against original and current updater functions."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as scoreboard

specification = importlib.util.spec_from_file_location('update_builder', ROOT / 'scripts/build_update_package.py')
builder = importlib.util.module_from_spec(specification)
specification.loader.exec_module(builder)

# Exact GPL-licensed upstream updater function from origin/main, version 1.3,
# commit d6d3a4a995c31480c748809b6ec7f13b3690b67e. Kept locally so shallow CI
# does not require fetching a remote branch or depending on current upstream.
LEGACY_UPDATER_SOURCE = r'''
def _apply_update_package(download_url, kiosk_token=None, kiosk_id=None):
    """
    Apply an update from download_url (a zip file).
    Falls back to git pull if the app lives in a git repo.
    Returns (ok: bool, message: str).
    """
    # Try git pull first when a .git directory exists
    if os.path.isdir(os.path.join(APP_DIR, '.git')):
        try:
            result = subprocess.run(
                ['git', '-C', APP_DIR, 'pull', '--rebase'],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return True, 'git pull succeeded: ' + result.stdout.strip()
        except Exception:
            pass  # Fall through to package download

    if not download_url:
        return False, 'No download URL provided and git pull is unavailable.'

    try:
        headers = {}
        if kiosk_token:
            headers['X-Kiosk-Token'] = kiosk_token
        if kiosk_id:
            headers['X-Kiosk-Id'] = kiosk_id
        r = requests.get(download_url, headers=headers, timeout=120, stream=True)
        r.raise_for_status()

        tmp = tempfile.mkdtemp()
        try:
            pkg = os.path.join(tmp, 'update.zip')
            with open(pkg, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            # Snapshot user-data files before extraction so they survive no matter what
            _PRESERVE_FILES = ['settings.json', 'kiosk.json', 'paired_kiosks.json']
            _snapshots = {}
            for fname in _PRESERVE_FILES:
                fpath = os.path.join(APP_DIR, fname)
                if os.path.exists(fpath):
                    with open(fpath, 'rb') as _f:
                        _snapshots[fname] = _f.read()

            with zipfile.ZipFile(pkg) as zf:
                names = zf.namelist()
                # Strip common top-level folder (GitHub zips include one)
                prefix = os.path.commonprefix(names).rstrip('/')
                for member in zf.infolist():
                    rel = member.filename
                    if prefix and rel.startswith(prefix + '/'):
                        rel = rel[len(prefix) + 1:]
                    if not rel:
                        continue
                    # Skip uploaded assets — never replace user media
                    if rel.startswith('static/uploads/'):
                        continue
                    target = os.path.join(APP_DIR, rel)
                    if member.is_dir():
                        os.makedirs(target, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            shutil.copyfileobj(src, dst)

            # Restore user-data files unconditionally — overrides anything extracted
            for fname, data in _snapshots.items():
                fpath = os.path.join(APP_DIR, fname)
                with open(fpath, 'wb') as _f:
                    _f.write(data)

            return True, 'Package extracted successfully.'
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        return False, str(e)
'''

LEGACY_CHECK_SOURCE = r'''
def _check_remote_version(source_url):
    """
    Fetch version info from source_url.
    Supports:
      - GitHub releases API  (api.github.com/repos/.../releases/latest)
      - Custom JSON endpoint ({ "version": "1.0.0.4", "download_url": "..." })
      - Bare version endpoint (just another scoreboard at /api/update/version)
    Returns (version_str, download_url, error_str).
    """
    source_url = source_url.strip().rstrip('/')
    # Accept a plain GitHub repo URL (e.g. pasted straight from the browser/git remote)
    # and translate it to the releases API endpoint instead of failing on its HTML page.
    gh_match = re.match(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$', source_url)
    if gh_match:
        source_url = f'https://api.github.com/repos/{gh_match.group(1)}/{gh_match.group(2)}/releases/latest'
    try:
        if 'api.github.com' in source_url:
            r = requests.get(source_url,
                             headers={'Accept': 'application/vnd.github.v3+json'},
                             timeout=10)
            r.raise_for_status()
            data = r.json()
            tag = data.get('tag_name', '')
            release_name = data.get('name', '')
            assets = data.get('assets', [])
            dl = next((a['browser_download_url'] for a in assets
                        if a['name'].endswith('.zip')), None)
            if not dl:
                dl = data.get('zipball_url', '')
            # tag_name may be a label ("secondfix") rather than a version number.
            # Extract a dotted version from tag_name first, then release name.
            _ver_re = re.compile(r'\d+\.\d+[\d.]*')
            ver_match = _ver_re.search(tag) or _ver_re.search(release_name)
            version_str = ver_match.group(0) if ver_match else tag
            return version_str, dl, None

        # Try as a scoreboard /api/update/version endpoint
        if source_url.endswith('/api/update/version') or '/api/update' not in source_url:
            probe_url = source_url if source_url.endswith('/api/update/version') \
                        else source_url + '/api/update/version'
            r = requests.get(probe_url, timeout=6)
            if r.ok:
                data = r.json()
                if 'version' in data:
                    dl = source_url.rstrip('/api/update/version').rstrip('/') + '/api/update/package'
                    return data['version'], dl, None

        # Generic JSON endpoint
        r = requests.get(source_url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get('version', ''), data.get('download_url', ''), None
    except Exception as e:
        return None, None, str(e)
'''


class Download:
    is_redirect = False

    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class UpdateDistributionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.installed = self.base / 'installed'
        self.installed.mkdir()
        self.package, self.digest = builder.build(self.base / 'output')
        self.body = self.package.read_bytes()
        self.seeded = {
            'settings.json': json.dumps({'teams': ['football/college-football:TA&M'],
                'color_mode': 'manual', 'colors': {'dark_bg': '#003322'}, 'city': '',
                'display_name': 'My GameDay', 'device_mode': 'server',
                'update': {'source_url': builder.ARTIFACT_BASE + 'update-manifest.json'}}).encode(),
            'kiosk.json': b'{"server_url":"http://old-server.local:5000","kiosk_id":"existing-kiosk","auth_token":"existing-fixture-token"}',
            'paired_kiosks.json': b'{"old-display":{"auth_token":"fixture-only"}}',
            '.session-key': b'x' * 32,
            'score_cache.json': b'{"saved_fixture":true}',
            'static/uploads/logo.png': b'private original GameDay logo fixture',
            'static/uploads/specials/promo.png': b'private promotion fixture',
            'start_kiosk.sh': b'#!/bin/sh\necho original custom kiosk command\n',
            'setup_kiosk_service.sh': b'original unit setup fixture\n',
            'install.sh': b'original installer fixture\n',
        }
        for relative, content in self.seeded.items():
            target = self.installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (self.installed / 'app.py').write_text('original_app = True\n')
        (self.installed / 'version.txt').write_text('1.3\n')
        (self.installed / 'requirements.txt').write_bytes((ROOT / 'requirements.txt').read_bytes())
        # Stand-ins are outside the app, like actual installed units/sudoers.
        self.unit = self.base / 'systemd' / 'kiosk.service'
        self.unit.parent.mkdir()
        self.unit.write_bytes(b'original systemd kiosk configuration')

    def assert_preserved(self):
        for relative, content in self.seeded.items():
            self.assertEqual((self.installed / relative).read_bytes(), content, relative)
        self.assertEqual(self.unit.read_bytes(), b'original systemd kiosk configuration')
        self.assertFalse((self.installed / '.git').exists())

    def assert_installed_runtime_starts(self):
        for relative in builder.RUNTIME_FILES:
            self.assertEqual((self.installed / relative).read_bytes(), (ROOT / relative).read_bytes(), relative)
        # Isolate imports from the development checkout and disable every worker.
        code = '''
import os
os.environ['WERKZEUG_RUN_MAIN'] = 'false'
import app
from pathlib import Path
assert Path(app.__file__).resolve().parent == Path.cwd()
assert Path(app.cfb_week.__file__).resolve().parent == Path.cwd()
def no_network(*args, **kwargs):
    raise AssertionError('Installed-runtime smoke test attempted network access')
app.requests.get = no_network
app.requests.post = no_network
app.get_weather = lambda city: ''
app._team_colors_for_league = lambda league: {}
client = app.app.test_client()
assert client.get('/api/ping').get_json()['ok'] is True
data = client.get('/api/data').get_json()
assert data['cfb_coverage'] == 'all_power5'
assert data['scorecard_filter'] == 'both'
assert data['scorecard_include_completed'] is False
assert data['display_name'] == 'My GameDay'
assert data['scorecard_empty_message']
assert client.get('/').status_code == 200
assert client.get('/static/js/display.js').status_code == 200
print('Installed runtime smoke passed')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=self.installed,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Installed runtime smoke passed', result.stdout)

    def test_runtime_package_is_flat_reproducible_and_excludes_device_startup_state(self):
        second, digest = builder.build(self.base / 'second')
        self.assertEqual(second.read_bytes(), self.body)
        self.assertEqual(digest, self.digest)
        with zipfile.ZipFile(io.BytesIO(self.body)) as archive:
            self.assertEqual(archive.namelist(), list(builder.RUNTIME_FILES))
            self.assertIsNone(archive.testzip())
        for forbidden in self.seeded:
            self.assertNotIn(forbidden, builder.RUNTIME_FILES)
        manifest = json.loads((self.base / 'output/update-manifest.json').read_text())
        self.assertEqual(manifest['sha256'], hashlib.sha256(self.body).hexdigest())
        self.assertEqual(manifest['download_url'], builder.ARTIFACT_BASE + self.package.name)

    def test_actual_original_upstream_13_zip_updater_preserves_data_and_installs_complete_runtime(self):
        module = ast.parse(LEGACY_UPDATER_SOURCE)
        download = Mock(return_value=Download(self.body))
        commands = Mock(side_effect=AssertionError('Original updater attempted git or a process'))
        namespace = {'APP_DIR': str(self.installed), 'os': os, 'requests': types.SimpleNamespace(get=download),
                     'subprocess': types.SimpleNamespace(run=commands), 'tempfile': tempfile,
                     'zipfile': zipfile, 'shutil': shutil}
        exec(compile(module, 'upstream-1.3-updater.py', 'exec'), namespace)
        ok, message = namespace['_apply_update_package']('https://reviewed.example/runtime.zip')
        self.assertTrue(ok, message)
        self.assert_preserved()
        self.assert_installed_runtime_starts()
        self.assert_preserved()
        download.assert_called_once()
        commands.assert_not_called()

    def test_current_updater_preserves_data_and_installs_complete_runtime(self):
        with patch.multiple(scoreboard, APP_DIR=str(self.installed),
                            SETTINGS_FILE=str(self.installed / 'settings.json'),
                            KIOSK_CONFIG_FILE=str(self.installed / 'kiosk.json')):
            with patch.object(scoreboard.requests, 'get', return_value=Download(self.body)) as download:
                ok, message = scoreboard._apply_update_package(builder.ARTIFACT_BASE + self.package.name)
        self.assertTrue(ok, message)
        self.assert_preserved()
        self.assert_installed_runtime_starts()
        self.assert_preserved()
        download.assert_called_once()
        self.assertTrue(list((self.installed / '.update-backups').glob('previous-*/app.py')))

    def test_original_and_current_update_checks_accept_the_published_json_manifest(self):
        manifest = json.loads((self.base / 'output/update-manifest.json').read_text())
        manifest_url = builder.ARTIFACT_BASE + 'update-manifest.json'
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                download = Mock(side_effect=[Mock(ok=False), Mock(ok=True, json=lambda: manifest)])
                if legacy:
                    namespace = {'requests': types.SimpleNamespace(get=download), 're': re}
                    exec(compile(ast.parse(LEGACY_CHECK_SOURCE), 'upstream-1.3-check.py', 'exec'), namespace)
                    result = namespace['_check_remote_version'](manifest_url)
                else:
                    with patch.object(scoreboard.requests, 'get', download):
                        result = scoreboard._check_remote_version(manifest_url)
                self.assertEqual(result, (manifest['version'], manifest['download_url'], None))
                self.assertEqual(download.call_args.args[0], manifest_url)

    def test_committed_artifact_matches_current_runtime_files_and_checksum(self):
        artifact = ROOT / 'artifacts' / self.package.name
        self.assertTrue(artifact.is_file(), 'Run python scripts/build_update_package.py before publication')
        self.assertEqual(artifact.read_bytes(), self.body, 'Runtime changed; rebuild the published ZIP')
        self.assertEqual((ROOT / 'artifacts/SHA256SUMS').read_text(), self.digest + '  ' + self.package.name + '\n')


if __name__ == '__main__':
    unittest.main()
