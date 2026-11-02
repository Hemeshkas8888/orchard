"""Which platforms a build covers: arguments, orchard.local.toml, the attached board; never all unless asked."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from orchard import distro, ram
from orchard.hardware import ROOT


class Selection(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / '.git').mkdir()
        attached = mock.patch('orchard.devices.attached_board', return_value=None)
        self.attached = attached.start()
        self.addCleanup(attached.stop)
        known = ram.boards_by_platform(ROOT)
        self.board_16k = sorted(known['apple-16k'])[0]
        self.board_4k = sorted(known['apple-4k'])[0]

    def local(self, text):
        (self.root / 'orchard.local.toml').write_text(text)

    def select(self, **options):
        return ram.resolve_platforms(self.root, ROOT, **options)

    def test_arguments_name_platforms_or_all(self):
        self.assertEqual(self.select(platforms=['apple-16k']), ['apple-16k'])
        self.assertEqual(self.select(platforms=['apple-4k', 'apple-16k', 'apple-4k']), ['apple-16k', 'apple-4k'])
        self.assertEqual(self.select(platforms=['all']), 'all')
        with self.assertRaisesRegex(ValueError, 'combines with no other'):
            self.select(platforms=['all', 'apple-16k'])
        with self.assertRaisesRegex(ValueError, 'Unknown platform nope'):
            self.select(platforms=['nope'])

    def test_a_device_selects_its_platform(self):
        self.assertEqual(self.select(device=self.board_4k), ['apple-4k'])

    def test_the_local_file_holds_sticky_defaults_for_the_same_arguments(self):
        self.local('platform = "apple-4k"\n')
        self.assertEqual(self.select(), ['apple-4k'])
        self.assertEqual(self.select(platforms=['apple-16k']), ['apple-16k'])  # the argument wins
        self.assertEqual(self.select(device=self.board_16k), ['apple-16k'])
        self.local('platform = "all"\n')
        self.assertEqual(self.select(), 'all')
        self.local(f'device = "{self.board_4k}"\n')
        self.assertEqual(self.select(), ['apple-4k'])

    def test_a_local_platform_and_device_must_agree(self):
        self.local(f'platform = "apple-16k"\ndevice = "{self.board_4k}"\n')
        with self.assertRaisesRegex(ValueError, 'is not a board of platform apple-16k'):
            self.select()

    def test_then_the_attached_board_else_a_question_never_all(self):
        self.attached.return_value = self.board_16k
        self.assertEqual(self.select(), ['apple-16k'])
        self.attached.return_value = None
        with self.assertRaisesRegex(ValueError, 'Which platform'):
            self.select()

    def test_a_payload_is_built_for_one_platform(self):
        self.local('platform = "all"\n')
        with self.assertRaisesRegex(ValueError, 'one platform'):
            ram.resolve_platform(self.root, ROOT)
        self.local('platform = "apple-4k"\n')
        self.assertEqual(ram.resolve_platform(self.root, ROOT), 'apple-4k')


class DistributionContract(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / '.git').mkdir()
        (self.root / 'tools').mkdir()
        (self.root / 'tools/build.py').write_text('')

    def distro(self, extra=''):
        (self.root / 'distro.toml').write_text(f'name = "fixture-linux"\nbuild = "tools/build.py"\n{extra}')

    def argv(self, **options):
        with mock.patch('orchard.distro.subprocess.run', side_effect=RuntimeError('stop')) as run:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                distro.build(self.root, version='dev-1', **options)
        return run.call_args[0][0]

    def test_selects_platform_is_a_boolean_setting(self):
        self.distro()
        self.assertFalse(distro.settings(self.root)['selects_platform'])
        self.distro('selects-platform = true\n')
        self.assertTrue(distro.settings(self.root)['selects_platform'])
        self.distro('selects-platform = "yes"\n')
        with self.assertRaisesRegex(ValueError, 'true or false'):
            distro.settings(self.root)

    def test_a_selecting_entry_gets_the_platforms(self):
        self.distro('selects-platform = true\n')
        self.assertEqual(self.argv(platforms=['apple-16k'])[-2:], ['--platform', 'apple-16k'])
        self.assertEqual(self.argv(platforms='all')[-2:], ['--platform', 'all'])
        with self.assertRaisesRegex(ValueError, 'selects its platforms'):
            distro.build(self.root, version='dev-2')

    def test_an_entry_that_builds_every_platform_keeps_working_and_gets_no_selection(self):
        self.distro()
        self.assertNotIn('--platform', self.argv())
        with self.assertRaisesRegex(ValueError, 'builds every platform'):
            distro.build(self.root, version='dev-3', platforms=['apple-16k'])


if __name__ == '__main__':
    unittest.main()
