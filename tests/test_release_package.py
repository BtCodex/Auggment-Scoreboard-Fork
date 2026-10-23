"""Exercise the actual release build block without publishing a release."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile


class ReleasePackagingTests(unittest.TestCase):
    def test_manual_upgrade_guide_includes_new_runtime_files(self):
        source = Path(__file__).resolve().parents[1]
        guide = (source/'docs/INSTALL_AND_ROLLBACK.md').read_text()
        paths = re.search(r"done <<'FILES'\n(.*?)\nFILES", guide, re.S)
        self.assertIsNotNone(paths)
        installed = set(paths.group(1).splitlines())
        self.assertTrue({'app.py', 'score_details.py', 'cfb_week.py', 'static/data/football-teams-2026.json',
                         'static/js/live-widgets.js', 'static/css/live-widgets.css'}.issubset(installed))
        self.assertIn('Do not use that older updater', guide)

    def test_actual_release_archive_contains_runtime_and_license_without_device_state(self):
        source = Path(__file__).resolve().parents[1]
        workflow = (source/'.github/workflows/release.yml').read_text()
        block = re.search(r'      - name: Build release zip\n        run: \|\n(.*?)(?=\n      - name:)', workflow, re.S)
        self.assertIsNotNone(block)
        script = textwrap.dedent(block.group(1)).replace('${{ steps.version.outputs.ver }}', 'test-1.3')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['app.py','score_details.py','cfb_week.py','install.sh','start_kiosk.sh','setup_kiosk_service.sh',
                         'requirements.txt','requirements-tested.txt','version.txt','LICENSE','README.md','QC_REPORT.md']:
                shutil.copyfile(source/name, root/name)
            for name in ['templates','static','scripts','docs','Images']:
                shutil.copytree(source/name, root/name, ignore=shutil.ignore_patterns('uploads','__pycache__'))
            subprocess.run(['bash','-e','-c',script],cwd=root,check=True,capture_output=True,text=True)
            with zipfile.ZipFile(root/'dist/Auggment-Scoreboard-test-1.3.zip') as archive:
                entries = {path.partition('/')[2] for path in archive.namelist()}
            for required in ['app.py','score_details.py','cfb_week.py','static/data/football-teams-2026.json','scripts/network_helper.py','static/js/clock.js','static/js/display.js',
                             'static/css/display-modes.css','static/css/live-widgets.css','static/js/live-widgets.js','templates/settings.html','LICENSE']:
                self.assertIn(required,entries)
            self.assertFalse(any(Path(path).name in ['settings.json','kiosk.json','paired_kiosks.json',
                                                    '.session-key','score_cache.json'] for path in entries))


if __name__ == '__main__':
    unittest.main()
