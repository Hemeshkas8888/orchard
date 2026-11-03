"""Builds and launches share the component cache; only cleanup takes it alone; an entry is built once."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from orchard import build

SRC = str(Path(__file__).resolve().parents[1] / 'src')
HOLD = '''
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from orchard import build
with build.component_lock(Path(sys.argv[2]), exclusive=sys.argv[3] == "exclusive"):
    print("held", flush=True)
    time.sleep(float(sys.argv[4]))
'''


class CacheConcurrency(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache)

    def hold(self, mode, seconds=1.0):
        holder = subprocess.Popen([sys.executable, '-c', HOLD, SRC, str(self.cache), mode, str(seconds)],
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.assertEqual(holder.stdout.readline().strip(), 'held')
        return holder

    def timed(self, **options):
        started = time.monotonic()
        with patch('sys.stderr', new=io.StringIO()):
            with build.component_lock(self.cache, **options):
                return time.monotonic() - started

    def test_a_launch_does_not_wait_for_a_running_build(self):
        self.hold('shared')
        self.assertLess(self.timed(), 0.5)

    def test_cleanup_waits_for_running_builds_and_builds_wait_for_cleanup(self):
        self.hold('shared')
        self.assertGreater(self.timed(exclusive=True), 0.5)
        self.hold('exclusive')
        self.assertGreater(self.timed(), 0.5)

    def test_one_entry_is_built_once_and_others_do_not_wait(self):
        calls, started = [], threading.Event()
        def slow(stage):
            calls.append('slow')
            started.set()
            time.sleep(1)
            (stage / 'artifact').write_text('one')
        def fast(stage):
            calls.append('fast')
            (stage / 'artifact').write_text('other')
        results = []
        first = threading.Thread(target=lambda: results.append(
            build.cached_component(self.cache, 'kernel', lambda: 'same', slow)))
        with patch('sys.stderr', new=io.StringIO()):
            first.start()
            started.wait(5)
            began = time.monotonic()
            build.cached_component(self.cache, 'pongo', lambda: 'other', fast)
            self.assertLess(time.monotonic() - began, 0.5)  # another entry: no waiting
            second = build.cached_component(self.cache, 'kernel', lambda: 'same',
                                            lambda stage: calls.append('again'))
            first.join(5)
        self.assertEqual(calls, ['slow', 'fast'])  # the same entry was built once
        self.assertEqual(second, results[0])
        self.assertEqual((second / 'artifact').read_text(), 'one')


if __name__ == '__main__':
    unittest.main()
