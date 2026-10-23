"""Exercise the documented copy block without sudo, systemd or a Raspberry Pi."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallationWorkflowTests(unittest.TestCase):
    def test_manual_zip_runtime_copy_preserves_private_state_and_startup_without_git(self):
        guide = (ROOT / 'docs/ZIP_UPDATE.md').read_text()
        declaration = re.search(r'```bash\n(FILES=\(.*?\n\))\n```', guide, re.S).group(1)
        block = re.search(r'<!-- BEGIN TESTED RUNTIME COPY -->\n```bash\n(.*?)\n```', guide, re.S).group(1)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            app = directory / 'existing'
            app.mkdir()
            protected = {'settings.json': b'{"colors":{"dark_bg":"#003300"},"teams":["saved"]}',
                         'kiosk.json': b'private pairing', 'paired_kiosks.json': b'private token',
                         '.session-key': b'private session', 'score_cache.json': b'saved scores',
                         'static/uploads/logo.png': b'actual custom dark green artwork',
                         'static/uploads/specials/promotion.png': b'custom promotion',
                         'start_kiosk.sh': b'original launch configuration',
                         'setup_kiosk_service.sh': b'original service setup',
                         'install.sh': b'original installer'}
            for relative, content in protected.items():
                target = app / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            command_directory = directory / 'bin'
            command_directory.mkdir()
            sudo = command_directory / 'sudo'
            sudo.write_text('#!/bin/sh\nexec "$@"\n')
            sudo.chmod(0o755)
            result = subprocess.run(['bash', '-eu', '-c', declaration + '\n' + block],
                env={**os.environ, 'PATH': str(command_directory) + os.pathsep + os.environ['PATH'],
                     'APP': str(app), 'CANDIDATE': str(ROOT),
                     'APP_USER': str(os.getuid()), 'APP_GROUP': str(os.getgid())},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((app / '.git').exists())
            for relative, content in protected.items():
                self.assertEqual((app / relative).read_bytes(), content, relative)
            for relative in ('app.py', 'cfb_week.py', 'score_details.py', 'static/js/display.js',
                             'static/data/football-teams-2026.json'):
                self.assertEqual((app / relative).read_bytes(), (ROOT / relative).read_bytes())

    def test_installer_handles_checkout_as_runtime_directory_without_same_file_copy(self):
        installer = (ROOT / 'install.sh').read_text()
        function = re.search(r'copy_if_exists\(\) \{.*?\n\}', installer, re.S).group()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.py'
            path.write_text('original = True\n')
            result = subprocess.run(['bash', '-eu', '-c', function + '\ncopy_if_exists "$1" "$1"',
                                     'check-copy', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('already in place', result.stdout)
            self.assertEqual(path.read_text(), 'original = True\n')


if __name__ == '__main__':
    unittest.main()
