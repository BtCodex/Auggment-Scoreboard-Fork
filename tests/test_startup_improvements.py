"""Startup checks never install packages, write /etc, or run a real browser."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scoreboard_network_helper', ROOT / 'scripts/network_helper.py')
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class ServiceGenerationTests(unittest.TestCase):
    def render(self, script, option, user='pi', directory='/home/pi/scoreboard', home='/home/pi'):
        return subprocess.run(['bash', str(ROOT / script), option, user, directory, home],
                              check=True, text=True, capture_output=True).stdout

    def test_backend_runs_without_online_network_and_recovers_at_bounded_rate(self):
        unit = self.render('install.sh', '--render-backend-unit')
        self.assertIn('WorkingDirectory=/home/pi/scoreboard\n', unit)
        self.assertIn('ExecStart=/usr/bin/python3 "/home/pi/scoreboard/app.py"', unit)
        self.assertIn('After=network.target', unit)
        self.assertNotIn('network-online.target', unit)
        self.assertIn('Restart=always', unit)
        self.assertIn('RestartSec=10', unit)
        self.assertIn('StartLimitIntervalSec=0', unit)
        self.assertIn('WantedBy=multi-user.target', unit)
        self.assertIn('UMask=0077', unit)

    def test_kiosk_has_no_graphical_target_ordering_cycle(self):
        unit = self.render('setup_kiosk_service.sh', '--render-unit')
        self.assertIn('After=display-manager.service scoreboard.service', unit)
        self.assertNotIn('After=graphical.target', unit)
        self.assertIn('Wants=scoreboard.service', unit)
        self.assertIn('RestartSec=15', unit)
        self.assertIn('WantedBy=graphical.target', unit)
        self.assertIn('WorkingDirectory=/home/pi/scoreboard\n', unit)
        self.assertIn('Environment="XAUTHORITY=/home/pi/.Xauthority"', unit)

    def test_actual_home_paths_and_systemd_percent_escaping(self):
        for script, option in [('install.sh', '--render-backend-unit'),
                               ('setup_kiosk_service.sh', '--render-unit')]:
            unit = self.render(script, option, directory='/srv/sports bar%/board', home='/srv/pi')
            self.assertIn('WorkingDirectory=/srv/sports bar%%/board\n', unit)
            self.assertIn('Environment="HOME=/srv/pi"', unit)
            self.assertNotIn('/home/pi', unit)

    def test_root_kiosk_and_invalid_service_user_are_rejected(self):
        for user in ['root', 'pi\nUser=root', 'pi;reboot']:
            result = subprocess.run(['bash', str(ROOT / 'setup_kiosk_service.sh'), '--render-unit',
                                     user, '/tmp/board', '/tmp/pi'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')

    def test_all_shell_scripts_have_valid_bash_syntax(self):
        for name in ('install.sh', 'start_kiosk.sh', 'setup_kiosk_service.sh'):
            subprocess.run(['bash', '-n', str(ROOT / name)], check=True, capture_output=True)

    def test_installer_uses_canonical_launcher_and_narrow_privileges(self):
        installer = (ROOT / 'install.sh').read_text()
        self.assertIn('copy_if_exists "$SCRIPT_DIR/start_kiosk.sh" "$APP_DIR/start_kiosk.sh"', installer)
        self.assertNotIn('cat > "$APP_DIR/start_kiosk.sh"', installer)
        self.assertIn('--render-unit "$APP_USER" "$APP_DIR" "$APP_HOME"', installer)
        self.assertIn('for asset_dir in css js;', installer)
        self.assertIn('systemctl set-default graphical.target', installer)
        self.assertIn('systemctl enable --force lightdm.service', installer)
        self.assertNotIn('ln -sf /lib/systemd/system/lightdm.service', installer)
        self.assertIn('[[ -f "$APP_DIR/static/uploads/logo.png" ]]', installer)
        self.assertNotIn('--no-sandbox', installer)
        self.assertNotIn('NOPASSWD: $WPA_CLI_PATH', installer)
        self.assertNotIn('NOPASSWD: $NMCLI_PATH', installer)
        self.assertIn('install -o root -g root -m 755', installer)
        self.assertIn('visudo -c -f "$SUDO_TMP"', installer)
        self.assertNotIn('chmod -R 755', installer)
        self.assertNotIn('systemctl disable --now apache2', installer)
        self.assertNotIn('addr add 192.168.1.250', installer)
        self.assertNotRegex(installer, re.compile(r'^\s*reboot\s*$', re.MULTILINE))


class ModeCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        installer = (ROOT / 'install.sh').read_text()
        marker = 'python3 - "$APP_DIR/settings.json" "$MODE" <<\'PYEOF\'\n'
        cls.initializer = installer.split(marker, 1)[1].split('\nPYEOF', 1)[0]

    def initialize(self, directory, mode):
        subprocess.run([shutil.which('python3'), '-', str(directory / 'settings.json'), mode],
                       input=self.initializer, text=True, check=True, capture_output=True)
        return json.loads((directory / 'settings.json').read_text())

    def test_new_server_combined_and_kiosk_initialize_explicit_mode_and_port(self):
        for mode, expected in [('server', ('server', 5000)), ('combined', ('server', 5000)),
                               ('kiosk', ('kiosk', 5001))]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                settings = self.initialize(Path(directory), mode)
                self.assertEqual((settings['device_mode'], settings['port']), expected)

    def test_existing_mode_port_favorites_and_theme_are_preserved(self):
        original = {'device_mode': 'server', 'port': 5017,
                    'favorites': {'football/college-football': ['245']},
                    'background_color': '#102818', 'custom': 'preserve me'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'settings.json').write_text(json.dumps(original))
            self.assertEqual(self.initialize(path, 'kiosk'), original)
            self.assertEqual((path / 'settings.json').read_text(), json.dumps(original))

    def test_corrupt_existing_settings_fail_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text('{broken')
            result = subprocess.run([shutil.which('python3'), '-', str(path), 'combined'],
                                    input=self.initializer, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), '{broken')


    def test_failed_atomic_mode_initialization_keeps_original_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            original = '{"favorites": {"football/nfl": ["34"]}}'
            path.write_text(original)
            failing_replace = "from unittest.mock import patch\npatch('os.replace', side_effect=OSError('disk full')).start()\n"
            result = subprocess.run([shutil.which('python3'), '-', str(path), 'combined'],
                                    input=failing_replace + self.initializer, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(directory).glob('.settings-*')), [])


class InstalledAssetTests(unittest.TestCase):
    def test_actual_installer_copy_sections_preserve_logo_and_install_all_scripts(self):
        installer = (ROOT / 'install.sh').read_text()
        copy_function = installer.split('copy_if_exists() {', 1)[1].split('\n# Find a file', 1)[0]
        copy_function = 'copy_if_exists() {' + copy_function
        assets = installer.split('# Copy application assets;', 1)[1].split('\n# version.txt', 1)[0]
        assets = '#' + assets
        logos = installer.split('# Default logo (templates reference', 1)[1].split('\n# ─── SYSTEMD:', 1)[0]
        logos = '# Default logo (templates reference' + logos
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            for base in [source, target]:
                for child in ['static/css', 'static/js', 'static/uploads', 'scripts']:
                    (base / child).mkdir(parents=True)
            for child, value in [('static/css/main.css', 'body{background:black}'),
                                 ('static/css/display-modes.css', '.ticker{}'),
                                 ('static/js/clock.js', 'clock'), ('static/js/display.js', 'display'),
                                 ('scripts/network_helper.py', '# network helper'),
                                 ('static/uploads/logo.png', 'unwanted new logo')]:
                (source / child).write_text(value)
            custom_logo = target / 'static/uploads/logo.png'
            custom_logo.write_bytes(b'original College GameDay logo')
            environment = dict(os.environ, SCRIPT_DIR=str(source), APP_DIR=str(target))
            subprocess.run(['bash', '-e'], input=copy_function + '\n' + assets + '\n' + logos,
                           env=environment, text=True, capture_output=True, check=True)
            self.assertEqual(custom_logo.read_bytes(), b'original College GameDay logo')
            for asset in ['static/css/main.css', 'static/css/display-modes.css',
                          'static/js/clock.js', 'static/js/display.js', 'scripts/network_helper.py']:
                self.assertEqual((source / asset).read_bytes(), (target / asset).read_bytes())


class KioskLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        shutil.copyfile(ROOT / 'start_kiosk.sh', self.directory / 'start_kiosk.sh')
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.write_command('id', 'echo 1000')
        self.write_command('sleep', 'exit 0')
        self.write_command('xset', 'exit 0')
        self.write_command('xrandr', 'echo "   1920x1080 60.0*+"')
        self.write_command('curl', 'exit 0')
        self.write_command('chromium', 'printf "%s\\n" "$@"')
        # Fail if the launcher regresses to terminating unrelated processes.
        self.write_command('pkill', 'echo unexpected-pkill >&2; exit 99')
        self.environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                                HOME=str(self.directory), KIOSK_TEST_DIR=str(self.directory))

    def write_command(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o700)

    def launch(self):
        return subprocess.run(['bash', str(self.directory / 'start_kiosk.sh')],
                              env=self.environment, text=True, capture_output=True, timeout=10)

    def test_configured_port_geometry_and_sandbox(self):
        (self.directory / 'settings.json').write_text(json.dumps({'port': 5017}))
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http://127.0.0.1:5017/?v=local', result.stdout)
        self.assertIn('--window-size=1920,1080', result.stdout)
        self.assertIn('--user-data-dir=' + str(self.directory), result.stdout)
        self.assertNotIn('--no-sandbox', result.stdout)
        self.assertNotIn('unexpected-pkill', result.stderr)

    def test_legacy_kiosk_fallback_and_bad_ports(self):
        (self.directory / 'kiosk.json').write_text('{}')
        for bad_port in [0, 65536, -1, True, '5000', '5017; reboot']:
            with self.subTest(port=bad_port):
                (self.directory / 'settings.json').write_text(json.dumps({'port': bad_port}))
                result = self.launch()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('http://127.0.0.1:5001/?v=', result.stdout)

    def test_late_backend_beyond_old_60_attempt_cutoff_is_awaited(self):
        self.write_command('curl', '''
count=$(cat "$KIOSK_TEST_DIR/probes" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$KIOSK_TEST_DIR/probes"
printf '%s\\n' "$@" >> "$KIOSK_TEST_DIR/curl-args"
[ "$count" -gt 65 ]
''')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / 'probes').read_text().strip(), '66')
        self.assertIn('Scoreboard is still starting', result.stdout)
        self.assertIn('--kiosk', result.stdout)
        probes = (self.directory / 'curl-args').read_text()
        self.assertIn('--connect-timeout\n2\n--max-time\n5', probes)

    def test_waits_for_actual_x11_session(self):
        self.write_command('xset', '''
if [ "$1" = q ]; then
  count=$(cat "$KIOSK_TEST_DIR/xprobes" 2>/dev/null || echo 0)
  count=$((count + 1)); echo "$count" > "$KIOSK_TEST_DIR/xprobes"
  [ "$count" -gt 3 ]; exit $?
fi
exit 0
''')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / 'xprobes').read_text().strip(), '4')
        self.assertIn('--kiosk', result.stdout)

    def test_root_and_missing_browser_fail_clearly(self):
        self.write_command('id', 'echo 0')
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular desktop user', result.stderr)
        self.write_command('id', 'echo 1000')
        self.environment['SCOREBOARD_BROWSER'] = '/no/such/browser'
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No Chromium/Chrome', result.stderr)

    def test_malformed_geometry_is_ignored(self):
        for geometry in ['1920xnot-a-height', 'not-a-widthx1080', '0x1080']:
            with self.subTest(geometry=geometry):
                self.write_command('xrandr', 'echo "' + geometry + ' 60*"')
                result = self.launch()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('--window-size', result.stdout)


class NetworkHelperTests(unittest.TestCase):
    def test_only_actual_valid_wireless_interfaces_are_accepted(self):
        with patch.object(network.Path, 'is_dir', return_value=True):
            self.assertTrue(network.valid_interface('wlan0'))
            self.assertTrue(network.valid_interface('wlp3s0'))
            for bad in ['../wlan0', '-i', 'wlan0 -a /tmp/root', 'wlan0\n', 'a' * 16]:
                self.assertFalse(network.valid_interface(bad))
        with patch.object(network.Path, 'is_dir', return_value=False):
            self.assertFalse(network.valid_interface('wlan0'))

    def test_existing_wifi_operation_shapes_are_supported(self):
        commands = [
            ['ip', 'link', 'set', 'wlan0', 'up'], ['iw', 'dev', 'wlan0', 'scan'],
            ['iwlist', 'wlan0', 'scan'], ['nmcli', 'device', 'set', 'wlan0', 'managed', 'yes'],
            ['nmcli', 'device', 'disconnect', 'wlan0'],
            ['nmcli', 'device', 'wifi', 'connect', 'Home Wi-Fi', 'ifname', 'wlan0'],
            ['nmcli', 'device', 'wifi', 'connect', 'Home Wi-Fi', 'ifname', 'wlan0', 'password', 'my password'],
            ['nmcli', '--escape', 'no', '-t', '-f', 'SSID,SIGNAL,SECURITY,ACTIVE', 'device', 'wifi', 'list', '--rescan', 'yes'],
        ]
        for operation in ['scan', 'scan_results', 'list_networks', 'add_network', 'disconnect', 'save_config']:
            commands.append(['wpa_cli', '-i', 'wlan0', operation])
        for operation in ['enable_network', 'disable_network', 'select_network', 'remove_network']:
            commands.append(['wpa_cli', '-i', 'wlan0', operation, '12'])
        for field, value in [('ssid', json.dumps('A "quoted" Wi-Fi')),
                             ('psk', json.dumps('password spaces')),
                             ('psk', 'a' * 64), ('key_mgmt', 'NONE')]:
            commands.append(['wpa_cli', '-i', 'wlan0', 'set_network', '12', field, value])
        with patch.object(network, 'valid_interface', return_value=True):
            for command in commands:
                with self.subTest(command=command[:3]):
                    self.assertEqual(network.validate_command(command), (command[0], command[1:]))

    def test_unrestricted_flags_executables_and_root_file_access_are_rejected(self):
        invalid = [
            ['/bin/sh', '-c', 'reboot'], ['wpa_cli', '-a', '/tmp/action'],
            ['wpa_cli', '-i', 'wlan0', '-a', '/tmp/action'],
            ['wpa_cli', '-i', 'wlan0', 'set_network', '1', 'ssid', '-a /tmp/action'],
            ['wpa_cli', '-i', 'wlan0', 'set_network', '1', 'ca_cert', '"/etc/shadow"'],
            ['wpa_cli', '-i', 'wlan0', 'enable_network', '1 -a /tmp/action'],
            ['nmcli', 'connection', 'import', 'type', 'vpn', 'file', '/tmp/config'],
            ['iw', 'dev', 'wlan0', 'set', 'type', 'monitor'],
            ['ip', 'link', 'set', 'wlan0', 'down'],
        ]
        with patch.object(network, 'valid_interface', return_value=True):
            for command in invalid:
                with self.subTest(command=command[:3]), self.assertRaises(ValueError):
                    network.validate_command(command)

    def test_tool_resolution_ignores_caller_path_and_environment(self):
        with patch.object(network, 'valid_interface', return_value=True), \
             patch.object(network.Path, 'is_file', return_value=True), \
             patch.object(network.os, 'access', return_value=True), \
             patch.object(network.os, 'execve') as execute:
            network.main(['iw', 'dev', 'wlan0', 'scan'])
            executable, argv, environment = execute.call_args.args
            self.assertEqual(executable, '/usr/sbin/iw')
            self.assertEqual(argv, ['/usr/sbin/iw', 'dev', 'wlan0', 'scan'])
            self.assertNotIn('PYTHONPATH', environment)
            self.assertNotIn('/tmp', environment['PATH'])


if __name__ == '__main__':
    unittest.main()
