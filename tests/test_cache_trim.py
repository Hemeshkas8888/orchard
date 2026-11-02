"""orchard cache --prune gives the Podman VM's freed space back to macOS, and never fails because of it."""
import io
import subprocess
import unittest
from unittest.mock import patch

from orchard import components


def run(results):
    calls = []
    def fake(argv, **_):
        calls.append(argv)
        code, out = results.pop(0)
        return subprocess.CompletedProcess(argv, code, out, '')
    return fake, calls


class TrimVM(unittest.TestCase):
    def trim(self, system='Darwin', results=()):
        fake, calls = run(list(results))
        with patch('platform.system', return_value=system), patch('shutil.which', return_value='/podman'), \
                patch('subprocess.run', side_effect=fake), patch('sys.stdout', new=io.StringIO()) as out:
            components.trim_vm()
        return calls, out.getvalue()

    def test_a_running_vm_is_trimmed(self):
        calls, out = self.trim(results=[(0, 'running\n'), (0, '/: 1 GiB trimmed\n')])
        self.assertEqual(calls[-1], ['podman', 'machine', 'ssh', 'sudo', 'fstrim', '-a'])
        self.assertIn('given back to macOS', out)

    def test_nothing_to_do_without_a_running_vm_or_off_macos(self):
        calls, out = self.trim(results=[(0, 'stopped\n')])
        self.assertEqual(len(calls), 1)
        self.assertIn('not running', out)
        calls, _ = self.trim(system='Linux')
        self.assertEqual(calls, [])

    def test_a_failed_trim_is_reported_not_raised(self):
        _, out = self.trim(results=[(0, 'running\n'), (1, '')])
        self.assertIn('Could not trim', out)


if __name__ == '__main__':
    unittest.main()
