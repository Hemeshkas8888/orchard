"""Outside a checkout, orchard runs the newest nightly, resolved per command; pinned or offline as asked."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ORCHARD = Path(__file__).resolve().parents[1] / 'bin/orchard'
NAME = 'nightly-20261103-0123456789ab'


@unittest.skipUnless(shutil.which('git') and shutil.which('curl') and shutil.which('uv'), 'needs git, curl, uv')
class ToolingVersion(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / 'pyproject.toml').write_text('[project]\nname = "orchard"\n')
        git = ['git', '-C', str(repo), '-c', 'user.email=t@example.invalid', '-c', 'user.name=t']
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'x', '--no-gpg-sign'], check=True)
        subprocess.run([*git, 'tag', NAME], check=True)
        (self.root / 'releases/nightly').mkdir(parents=True)
        (self.root / 'releases/nightly/latest.json').write_text(f'{{"schema": 1, "name": "{NAME}"}}\n')
        (self.root / 'work').mkdir()

    def checkout(self, releases='releases', cwd='work', action='checkout', **env):
        result = subprocess.run([str(ORCHARD), action], cwd=self.root / cwd, capture_output=True, text=True,
                                env={**os.environ, 'ORCHARD_CACHE_DIR': str(self.root / 'cache'),
                                     'ORCHARD_MAINLINE_URL': f'file://{self.root}/repo',
                                     'ORCHARD_RELEASES_URL': f'file://{self.root}/{releases}', **env})
        return result

    def test_the_newest_nightly_then_offline_the_cached_one(self):
        result = self.checkout()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        offline = self.checkout(releases='nowhere')
        self.assertEqual(offline.stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        self.assertIn('no network', offline.stderr)

    def test_no_nightly_yet_or_asked_is_mainline(self):
        self.assertEqual(self.checkout(releases='nowhere').stdout.strip(), str(self.root / 'cache/orchard-main'))
        self.assertEqual(self.checkout(ORCHARD_TOOLING='mainline').stdout.strip(),
                         str(self.root / 'cache/orchard-main'))

    def test_a_pinned_version_and_an_unknown_one(self):
        (self.root / 'work/orchard.local.toml').write_text(f'orchard = "{NAME}"\n')
        self.assertEqual(self.checkout(releases='nowhere').stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        (self.root / 'work/orchard.local.toml').write_text('orchard = "v9.9.9"\n')
        result = self.checkout()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no orchard version v9.9.9', result.stderr)

    def test_an_older_launcher_says_so_and_update_moves_it_to_the_nightly(self):
        result = self.checkout()
        self.assertIn(f'a newer launcher is in {NAME}', result.stderr)
        update = self.checkout(action='update')
        self.assertEqual(update.returncode, 0, update.stderr)
        self.assertNotIn('newer launcher', update.stderr)
        head = subprocess.run(['git', '-C', str(self.root / 'cache/orchard-main'), 'describe', '--tags'],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, NAME)


if __name__ == '__main__':
    unittest.main()
