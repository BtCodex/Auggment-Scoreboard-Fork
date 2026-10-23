"""Deterministic security and safe-update checks; no network or Pi access."""
import base64
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as scoreboard

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


class SecurityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key, value in {'APP_DIR': str(self.root),
                           'SETTINGS_FILE': str(self.root / 'settings.json'),
                           'KIOSK_CONFIG_FILE': str(self.root / 'kiosk.json'),
                           'KIOSKS_FILE': str(self.root / 'paired_kiosks.json'),
                           'UPLOAD_FOLDER': str(self.root / 'uploads'),
                           'SPECIALS_FOLDER': str(self.root / 'uploads/specials'),
                           'RSS_LOGOS_FOLDER': str(self.root / 'uploads/rss_logos'),
                           '_auth_failures': {}}.items():
            patcher = patch.object(scoreboard, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = scoreboard.app.test_client()
        with self.client.session_transaction() as state:
            state['user'] = 'admin'

    def write_legacy_credentials(self, password='old-password'):
        Path(scoreboard.SETTINGS_FILE).write_text(json.dumps({
            'teams': ['football/nfl:34'], 'admin_credentials': {'username': 'admin', 'password': password}}))

    def package(self, files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)
        response = Mock()
        response.iter_content.return_value = [buffer.getvalue()]
        return patch.object(scoreboard.requests, 'get', return_value=response)

    def prepare_update(self):
        (self.root / 'app.py').write_text('old_code = True\n')
        (self.root / 'version.txt').write_text('1.0\n')
        scoreboard.save_settings({'teams': ['saved favorite'],
                                  'update': {'source_url': 'https://reviewed.example/release'}})

    def test_missing_runtime_modules_reject_update_before_any_file_changes(self):
        self.prepare_update()
        before = (self.root / 'app.py').read_bytes()
        for program in ('import cfb_week\n', 'from score_details import ScoreDetailsCache\n'):
            with self.subTest(program=program), self.package({'app.py': program, 'version.txt': '9.0'}):
                ok, message = scoreboard._apply_update_package('https://reviewed.example/app.zip')
                self.assertFalse(ok)
                self.assertIn('missing required module', message)
                self.assertEqual((self.root / 'app.py').read_bytes(), before)
                self.assertEqual((self.root / 'version.txt').read_text(), '1.0\n')

    def test_settings_require_authentication_and_redact_all_credentials(self):
        self.write_legacy_credentials()
        self.assertEqual(scoreboard.app.test_client().get('/api/settings').status_code, 401)
        response = self.client.get('/api/settings')
        credentials = response.get_json()['admin_credentials']
        self.assertEqual(credentials, {'username': 'admin', 'password_set': True, 'default_password': False})
        self.assertNotIn(b'old-password', response.data)
        self.assertNotIn('auth_token', response.get_json())

    def test_legacy_password_is_hashed_after_successful_login(self):
        self.write_legacy_credentials()
        with patch.object(scoreboard.subprocess, 'run') as command:
            self.assertFalse(scoreboard.authenticate_linux_user('root', 'anything'))
            self.assertFalse(scoreboard.authenticate_linux_user('admin', 'wrong'))
            self.assertTrue(scoreboard.authenticate_linux_user('admin', 'old-password'))
            command.assert_not_called()
        saved = json.loads(Path(scoreboard.SETTINGS_FILE).read_text())
        self.assertNotIn('password', saved['admin_credentials'])
        self.assertNotIn('old-password', Path(scoreboard.SETTINGS_FILE).read_text())
        self.assertTrue(scoreboard.authenticate_linux_user('admin', 'old-password'))
        self.assertEqual(saved['teams'], ['football/nfl:34'])
        self.assertEqual(stat.S_IMODE(Path(scoreboard.SETTINGS_FILE).stat().st_mode), 0o600)

    def test_password_change_and_blank_retention_survive_new_clients(self):
        response = self.client.post('/api/settings', json={'admin_credentials': {
            'username': 'owner', 'password': 'a long new password'}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post('/api/settings', json={'admin_credentials': {
            'username': 'owner', 'password': ''}}).status_code, 200)
        anonymous = scoreboard.app.test_client()
        self.assertEqual(anonymous.post('/login', data={
            'username': 'owner', 'password': 'a long new password'}).status_code, 302)
        self.assertEqual(anonymous.get('/api/settings').status_code, 200)
        self.assertFalse(scoreboard.authenticate_linux_user('admin', 'root'))

    def test_invalid_credentials_do_not_overwrite_saved_preferences(self):
        self.write_legacy_credentials()
        before = Path(scoreboard.SETTINGS_FILE).read_bytes()
        for credentials in ({'username': ''}, {'password': 'short'}, {'password_hash': 'chosen hash'}):
            with self.subTest(credentials=credentials):
                self.assertEqual(self.client.post('/api/settings', json={
                    'admin_credentials': credentials}).status_code, 400)
                self.assertEqual(Path(scoreboard.SETTINGS_FILE).read_bytes(), before)

    def test_authentication_backoff_prevents_unbounded_hash_work(self):
        anonymous = scoreboard.app.test_client()
        with patch.object(scoreboard, 'authenticate_linux_user', return_value=False) as authenticate:
            for _ in range(20):
                self.assertEqual(anonymous.post('/api/auth', json={
                    'username': 'admin', 'password': 'bad'}).status_code, 401)
            self.assertEqual(authenticate.call_count, 10)
            with patch.object(scoreboard.time_module, 'monotonic', return_value=10**12):
                anonymous.post('/api/auth', json={'username': 'admin', 'password': 'bad'})
            self.assertEqual(authenticate.call_count, 11)
        self.assertEqual(anonymous.post('/api/auth', json=['bad']).status_code, 400)

    def test_cross_site_changes_rejected_and_same_origin_supported(self):
        self.assertEqual(self.client.post('/api/settings', json={'clock_format': 'hidden'},
                                         headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings', json={'clock_format': 'hidden'},
                                         headers={'Origin': 'http://localhost'}).status_code, 200)
        self.assertEqual(self.client.post('/api/settings', json={'clock_format': '12h'},
                                         headers={'Referer': 'http://localhost/settings'}).status_code, 200)
        self.assertEqual(self.client.post('/api/settings', json={},
                                         headers={'Origin': 'http://[invalid'}).status_code, 403)
        # Public pairing deliberately supports another local display's origin.
        self.assertEqual(self.client.post('/api/pairing/claim', json={},
                                         headers={'Origin': 'http://other-display'}).status_code, 400)

    def test_session_key_private_persistent_and_not_the_old_known_key(self):
        path = self.root / '.session-key'
        first = scoreboard._load_session_key(str(path))
        self.assertEqual(len(first), 32)
        self.assertEqual(first, scoreboard._load_session_key(str(path)))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotEqual(scoreboard.app.secret_key, 'scoreboard_internal_secure_key')

    def test_old_known_signing_key_cannot_forge_admin_session(self):
        from flask import Flask
        old_app = Flask('old-app')
        old_app.secret_key = 'scoreboard_internal_secure_key'
        cookie = scoreboard.app.session_interface.get_signing_serializer(old_app).dumps({'user': 'admin'})
        anonymous = scoreboard.app.test_client()
        anonymous.set_cookie('session', cookie)
        self.assertEqual(anonymous.get('/api/settings').status_code, 401)

    def test_uploaded_logo_is_validated_and_only_explicit_removal_deletes_it(self):
        self.assertEqual(self.client.post('/api/upload_logo', data={
            'logo': (io.BytesIO(PNG), 'custom College GameDay.png')}).status_code, 200)
        logo = Path(scoreboard.UPLOAD_FOLDER) / 'logo.png'
        self.assertEqual(logo.read_bytes(), PNG)
        for contents, filename in [(b'<svg onload="alert(1)"></svg>', 'attack.svg'),
                                   (b'<html>bad</html>', 'looks-like.png'),
                                   (PNG[:-10], 'truncated.png'),
                                   (b'x' * (8 * 1024 * 1024 + 1), 'huge.jpg')]:
            with self.subTest(filename=filename):
                response = self.client.post('/api/upload_logo', data={
                    'logo': (io.BytesIO(contents), filename)})
                try:
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(logo.read_bytes(), PNG)
                finally:
                    response.request.input_stream.close()
                    response.close()
        self.client.post('/api/settings', json={'show_logo_slide': False})
        self.assertEqual(logo.read_bytes(), PNG)
        self.assertEqual(scoreboard.app.test_client().delete('/api/logo').status_code, 401)
        self.assertEqual(self.client.delete('/api/logo').status_code, 200)
        self.assertFalse(logo.exists())
        self.assertEqual(self.client.delete('/api/logo').status_code, 200)

    def test_special_upload_uses_actual_type_and_no_path_from_filename(self):
        response = self.client.post('/api/upload_special_image', data={
            'image': (io.BytesIO(PNG), '../../outside.html')})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['url'].endswith('.png'))
        self.assertFalse((self.root / 'outside.html').exists())
        self.assertEqual(len(list(Path(scoreboard.SPECIALS_FOLDER).glob('*.png'))), 1)

    def test_kiosk_and_registry_saves_retain_old_files_when_replace_fails(self):
        scoreboard.save_kiosk_config({'server_url': 'http://first.local', 'auth_token': 'private-token'})
        scoreboard.save_kiosks({'display': {'auth_token': 'private-token'}})
        for path, operation in [(Path(scoreboard.KIOSK_CONFIG_FILE), lambda: scoreboard.save_kiosk_config({'server_url': 'http://new.local'})),
                                (Path(scoreboard.KIOSKS_FILE), lambda: scoreboard.save_kiosks({}))]:
            with self.subTest(path=path.name):
                before = path.read_bytes()
                with patch.object(scoreboard.os, 'replace', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):
                        operation()
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_paired_kiosk_id_alone_never_authenticates(self):
        scoreboard.save_kiosks({'display': {'auth_token': 'correct-token'}})
        anonymous = scoreboard.app.test_client()
        self.assertEqual(anonymous.get('/api/update/package', headers={'X-Kiosk-Id': 'display'}).status_code, 401)
        self.assertEqual(anonymous.post('/api/kiosks/display/heartbeat').status_code, 401)
        self.assertEqual(anonymous.post('/api/kiosks/display/heartbeat', headers={
            'X-Kiosk-Id': 'display', 'X-Kiosk-Token': 'wrong'}).status_code, 401)
        self.assertEqual(anonymous.post('/api/kiosks/display/heartbeat', headers={
            'X-Kiosk-Id': 'display', 'X-Kiosk-Token': 'correct-token'}).status_code, 200)
        self.assertEqual(anonymous.post('/api/kiosks/another/heartbeat', headers={
            'X-Kiosk-Token': 'correct-token'}).status_code, 401)

    def test_updates_refuse_git_checkouts_default_upstream_and_public_http(self):
        (self.root / '.git').mkdir()
        with patch.object(scoreboard.requests, 'get') as download, patch.object(scoreboard.subprocess, 'run') as command:
            self.assertFalse(scoreboard._apply_update_package('https://reviewed.example/app.zip')[0])
            (self.root / '.git').rmdir()
            self.assertFalse(scoreboard._apply_update_package('https://upstream.example/app.zip')[0])
            scoreboard.save_settings({'update': {'source_url': 'https://reviewed.example/release'}})
            self.assertFalse(scoreboard._apply_update_package('http://example.org/app.zip')[0])
            download.assert_not_called()
            command.assert_not_called()

    def test_reviewed_package_updates_code_and_preserves_all_device_data(self):
        self.prepare_update()
        for name in ('kiosk.json', 'paired_kiosks.json', 'score_cache.json', '.session-key'):
            (self.root / name).write_bytes(b'preserve me')
        uploads = self.root / 'static/uploads'
        uploads.mkdir(parents=True)
        (uploads / 'logo.png').write_bytes(PNG)
        files = {'release/app.py': 'new_code = True\n', 'release/version.txt': '2.0\n',
                 'release/settings.json': 'overwrite', 'release/kiosk.json': 'overwrite',
                 'release/paired_kiosks.json': 'overwrite', 'release/score_cache.json': 'overwrite',
                 'release/.session-key': 'overwrite', 'release/static/uploads/logo.png': 'overwrite',
                 'release/LICENSE': 'license fixture'}
        before = Path(scoreboard.SETTINGS_FILE).read_bytes()
        with self.package(files):
            ok, message = scoreboard._apply_update_package('https://reviewed.example/app.zip')
        self.assertTrue(ok, message)
        self.assertEqual((self.root / 'app.py').read_text(), 'new_code = True\n')
        self.assertEqual(Path(scoreboard.SETTINGS_FILE).read_bytes(), before)
        self.assertEqual((uploads / 'logo.png').read_bytes(), PNG)
        for name in ('kiosk.json', 'paired_kiosks.json', 'score_cache.json', '.session-key'):
            self.assertEqual((self.root / name).read_bytes(), b'preserve me')
        self.assertEqual(len(list((self.root / '.update-backups').glob('previous-*/app.py'))), 1)

    def test_update_traversal_symlinks_invalid_python_and_dependency_changes_fail_before_writes(self):
        self.prepare_update()
        symlink = zipfile.ZipInfo('templates/escape.html')
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fixtures = [
            {'app.py': 'new_code = True\n', '../outside.py': 'bad'},
            {'app.py': 'new_code = True\n', '/tmp/outside.py': 'bad'},
            {'app.py': 'new_code = True\n', symlink: '../../outside'},
            {'app.py': 'this is invalid python !'},
            {'app.py': 'new_code = True\n', 'requirements.txt': 'unreviewed-dependency'},
        ]
        (self.root / 'requirements.txt').write_text('Flask\n')
        for files in fixtures:
            with self.subTest(files=list(files)):
                with self.package(files):
                    ok, _ = scoreboard._apply_update_package('https://reviewed.example/app.zip')
                self.assertFalse(ok)
                self.assertEqual((self.root / 'app.py').read_text(), 'old_code = True\n')

    def test_partial_update_failure_rolls_back_previous_code(self):
        self.prepare_update()
        original_replace = scoreboard.os.replace
        def replace_once(source, destination):
            if str(destination).endswith('/version.txt'):
                raise OSError('simulated disk error')
            return original_replace(source, destination)
        with self.package({'app.py': 'new_code = True\n', 'version.txt': '2.0\n'}):
            with patch.object(scoreboard.os, 'replace', side_effect=replace_once):
                ok, message = scoreboard._apply_update_package('https://reviewed.example/app.zip')
        self.assertFalse(ok)
        self.assertIn('simulated disk error', message)
        self.assertEqual((self.root / 'app.py').read_text(), 'old_code = True\n')
        self.assertEqual((self.root / 'version.txt').read_text(), '1.0\n')

    def test_kiosk_tokens_are_not_sent_to_unrelated_update_hosts(self):
        self.prepare_update()
        scoreboard.save_kiosk_config({'server_url': 'http://scoreboard.local'})
        with self.package({'app.py': 'new_code = True\n'}) as download:
            self.assertTrue(scoreboard._apply_update_package('https://releases.example/app.zip', 'secret-token', 'display')[0])
            self.assertNotIn('X-Kiosk-Token', download.call_args.kwargs['headers'])

    def test_wifi_rejects_malformed_credentials_without_host_commands(self):
        with patch.object(scoreboard, '_wifi_tool') as tool:
            for data in ([], {'ssid': ''}, {'ssid': 'a' * 33}, {'ssid': 'network\ncommand'},
                         {'ssid': 'network', 'password': 'short'}, {'ssid': 'network', 'password': 7}):
                with self.subTest(data=data):
                    self.assertEqual(self.client.post('/api/wifi/connect', json=data).status_code, 400)
            tool.assert_not_called()

    def test_privileged_network_retry_only_uses_reviewed_helper(self):
        failure = Mock(returncode=1)
        success = Mock(returncode=0)
        with patch.object(scoreboard.subprocess, 'run', side_effect=[failure, success]) as command:
            self.assertIs(scoreboard._run(['iw', 'dev', 'wlan0', 'scan']), success)
            self.assertEqual(command.call_args.args[0], [
                'sudo', '-n', '/usr/local/libexec/scoreboard-network', 'iw', 'dev', 'wlan0', 'scan'])

    def test_password_changes_revoke_other_sessions_and_support_unicode(self):
        self.write_legacy_credentials()
        self.assertEqual(self.client.get('/api/settings').status_code, 200)
        other = scoreboard.app.test_client()
        self.assertEqual(other.post('/login', data={'username': 'admin', 'password': 'old-password'}).status_code, 302)
        # Login migration changed the credential version; renew the initiating session.
        self.client.post('/login', data={'username': 'admin', 'password': 'old-password'})
        self.assertEqual(self.client.post('/api/settings', json={'admin_credentials': {
            'username': 'José', 'password': 'café testing phrase'}}).status_code, 200)
        self.assertEqual(self.client.get('/api/settings').status_code, 200)
        self.assertEqual(other.get('/api/settings').status_code, 401)
        self.assertTrue(scoreboard.authenticate_linux_user('José', 'café testing phrase'))

    def test_corrupt_credentials_fail_closed_without_resetting_to_default_password(self):
        Path(scoreboard.SETTINGS_FILE).write_text('{invalid JSON')
        self.assertFalse(scoreboard.authenticate_linux_user('admin', 'root'))
        Path(scoreboard.SETTINGS_FILE).write_text(json.dumps({'admin_credentials': {'username': 42, 'password': 'bad'}}))
        self.assertFalse(scoreboard.authenticate_linux_user('admin', 'root'))
        Path(scoreboard.SETTINGS_FILE).write_text(json.dumps({'admin_credentials': {
            'username': 'admin', 'password_hash': 'unsupported-method$salt$hash'}}))
        self.assertFalse(scoreboard.authenticate_linux_user('admin', 'root'))
        self.assertEqual(self.client.get('/api/settings').status_code, 200)

    def test_same_server_update_download_refuses_credential_redirects(self):
        self.prepare_update()
        scoreboard.save_kiosk_config({'server_url': 'http://scoreboard.local'})
        with self.package({'app.py': 'new_code = True\n'}) as download:
            download.return_value.is_redirect = True
            ok, _ = scoreboard._apply_update_package('http://scoreboard.local/api/update/package', 'secret-token', 'display')
            self.assertFalse(ok)
            self.assertFalse(download.call_args.kwargs['allow_redirects'])
            self.assertEqual((self.root / 'app.py').read_text(), 'old_code = True\n')

    def test_update_preserves_installed_script_permissions(self):
        self.prepare_update()
        launcher = self.root / 'start_kiosk.sh'
        launcher.write_text('#!/bin/bash\necho old\n')
        launcher.chmod(0o755)
        with self.package({'app.py': 'new_code = True\n', 'start_kiosk.sh': '#!/bin/bash\necho new\n'}):
            ok, message = scoreboard._apply_update_package('https://reviewed.example/app.zip')
        self.assertTrue(ok, message)
        self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), 0o755)

    def test_exported_update_includes_license_startup_source_and_no_secrets(self):
        for name in ('app.py', 'LICENSE', 'install.sh', 'start_kiosk.sh', 'setup_kiosk_service.sh', 'init_display.sh'):
            (self.root / name).write_text('source fixture')
        scripts = self.root / 'scripts'
        scripts.mkdir()
        (scripts / 'network_helper.py').write_text('source fixture')
        (scripts / 'generated.pyc').write_bytes(b'generated artifact')
        (self.root / '.session-key').write_bytes(b'private secret')
        response = self.client.get('/api/update/package')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = archive.namelist()
        for name in ('LICENSE', 'install.sh', 'start_kiosk.sh', 'setup_kiosk_service.sh', 'init_display.sh', 'scripts/network_helper.py'):
            self.assertIn(name, names)
        self.assertNotIn('.session-key', names)
        self.assertNotIn('scripts/generated.pyc', names)

    def test_pairing_endpoints_reject_malformed_payloads_without_network_or_state_changes(self):
        scoreboard.save_kiosks({'display': {'auth_token': 'correct-token'}})
        with patch.object(scoreboard.requests, 'post') as network:
            for path in ('/api/pairing/claim', '/api/pairing/connect', '/api/kiosks/display/heartbeat'):
                for payload in ([1], {'code': ['bad']}, {'code': 5}, {'kiosk_id': {}}, {'kiosk_url': 4}):
                    with self.subTest(path=path, payload=payload):
                        self.assertEqual(self.client.post(path, json=payload, headers={
                            'X-Kiosk-Token': 'correct-token'}).status_code, 400)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
