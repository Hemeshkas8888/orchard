"""orchard build records what it ran, cache hits included, as a plain script."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from orchard import build, explain  # noqa: E402


class Explain(unittest.TestCase):
    def test_a_cache_hit_lists_the_commands_that_produced_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            key = build.keyed(lambda: {'x': 1})
            def produce(stage):
                explain.command(['/bin/sh', '-c', 'true', str(stage / 'out')])
                (stage / 'out').write_text('result')
            explain.start()
            target = build.cached_component(cache, 'thing', key, produce)
            first = explain.stop()
            recorded = json.loads((target / explain.COMMANDS).read_text())
            self.assertEqual(recorded, [{'run': ['/bin/sh', '-c', 'true', '$ENTRY/out']}])
            explain.start()
            build.cached_component(cache, 'thing', key, produce)
            second = explain.stop()
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]['run'][:3], ['/bin/sh', '-c', 'true'])
            self.assertEqual(second[-1], {'run': ['/bin/sh', '-c', 'true', f'{target}/out']})
            self.assertIn('reused from the cache', second[0]['note'])

    def test_orchard_internals_are_marked_not_standalone(self):
        text = explain.script([{'run': [sys.executable, '-m', 'orchard.image.recovery']},
                               {'run': [sys.executable, '/x/assemble.py', '--bootargs', 'a b']},
                               {'note': 'a note'}], title='t')
        lines = text.splitlines()
        self.assertIn("# not standalone yet: runs orchard's Python module orchard.image.recovery", lines)
        self.assertIn('"$PYTHON" /x/assemble.py --bootargs \'a b\'', lines)
        self.assertEqual(sum(line.startswith('# not standalone') for line in lines), 1)
        self.assertIn('# a note', lines)


if __name__ == '__main__':
    unittest.main()
