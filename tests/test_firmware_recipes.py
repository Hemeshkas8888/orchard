"""Every described board's firmware recipe keeps the format its consumers rely on.

Distributions read these recipes (their audits list every board's outputs),
so a recipe outside the schema breaks them without failing anything else here.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECIPES = sorted(ROOT.glob('devices/*/firmware.json'))


class FirmwareRecipes(unittest.TestCase):
    def test_every_board_with_a_descriptor_has_a_recipe(self):
        for descriptor in sorted(ROOT.glob('devices/*/device.toml')):
            with self.subTest(board=descriptor.parent.name):
                self.assertTrue((descriptor.parent / 'firmware.json').is_file())

    def test_every_recipe_has_the_fields_consumers_read(self):
        for path in RECIPES:
            with self.subTest(board=path.parent.name):
                recipe = json.loads(path.read_text())
                self.assertEqual(recipe.get('schema'), 2)
                self.assertIsInstance(recipe.get('inputs'), dict)
                self.assertIsInstance(recipe.get('outputs'), list)
                for output in recipe['outputs']:
                    self.assertTrue(output['destination'].startswith('lib/firmware/'))

    def test_every_recipe_matches_the_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is an optional development dependency')
        schema = json.loads((ROOT / 'schemas/v1/firmware.schema.json').read_text())
        for path in RECIPES:
            with self.subTest(board=path.parent.name):
                jsonschema.validate(json.loads(path.read_text()), schema, cls=jsonschema.Draft202012Validator)


if __name__ == '__main__':
    unittest.main()
