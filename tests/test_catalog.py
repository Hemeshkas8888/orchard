"""The catalog stays consistent: boards, chips, methods, boot recipes and the matrix."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTORS = sorted(ROOT.glob('devices/*/device.toml'))
CHIPS = {chip['cpid']: chip for chip in (tomllib.loads(path.read_text()) for path in (ROOT / 'chips').glob('*.toml'))}
METHODS = tomllib.loads((ROOT / 'methods.toml').read_text())


def tool():
    loader = importlib.machinery.SourceFileLoader('catalog_generate', str(ROOT / 'tools/catalog/generate'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Catalog(unittest.TestCase):
    def test_every_board_is_on_a_known_chip(self):
        for path in DESCRIPTORS:
            with self.subTest(board=path.parent.name):
                self.assertIn(tomllib.loads(path.read_text())['match']['dfu']['chip'], CHIPS)

    def test_a_board_uses_its_chips_platform(self):
        for path in DESCRIPTORS:
            described = tomllib.loads(path.read_text())
            if 'kernel' in described:
                with self.subTest(board=path.parent.name):
                    self.assertEqual(described['kernel']['platform'],
                                     CHIPS[described['match']['dfu']['chip']].get('platform'))

    def test_a_chip_names_a_platform_that_exists(self):
        for chip in CHIPS.values():
            if 'platform' in chip:
                with self.subTest(chip=chip['soc']):
                    self.assertTrue((ROOT / 'platforms' / f'{chip["platform"]}.toml').is_file())

    def test_the_file_name_is_the_soc(self):
        for path in (ROOT / 'chips').glob('*.toml'):
            with self.subTest(chip=path.stem):
                self.assertEqual(tomllib.loads(path.read_text())['soc'], path.stem)

    def test_a_board_lists_only_known_methods(self):
        for path in DESCRIPTORS:
            with self.subTest(board=path.parent.name):
                for method in tomllib.loads(path.read_text()).get('boot', {}).get('methods', []):
                    self.assertIn(method, METHODS)

    def test_a_method_that_needs_boot_json_has_one(self):
        for path in DESCRIPTORS:
            for method in tomllib.loads(path.read_text()).get('boot', {}).get('methods', []):
                if METHODS[method]['boot_json']:
                    with self.subTest(board=path.parent.name, method=method):
                        recipe = json.loads((path.parent / 'boot.json').read_text())
                        self.assertIn(method, recipe['methods'])

    def test_a_boot_recipe_belongs_to_its_board(self):
        for path in sorted(ROOT.glob('devices/*/boot.json')):
            with self.subTest(board=path.parent.name):
                recipe = json.loads(path.read_text())
                described = tomllib.loads((path.parent / 'device.toml').read_text())
                self.assertIn(recipe['device'], described['device']['apple_products'])
                builds = {entry['ipsw']['build'] for entry in recipe['firmware']}
                for method, data in recipe['methods'].items():
                    self.assertIn(method, METHODS)
                    if 'build' in data:
                        self.assertIn(data['build'], builds)

    def test_files_validate_against_their_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is an optional development dependency')
        chip = Draft202012Validator(json.loads((ROOT / 'schemas/v1/chip.schema.json').read_text()))
        recipe = Draft202012Validator(json.loads((ROOT / 'schemas/v1/boot-recipe.schema.json').read_text()))
        for value in CHIPS.values():
            chip.validate(value)
        for path in sorted(ROOT.glob('devices/*/boot.json')):
            with self.subTest(board=path.parent.name):
                recipe.validate(json.loads(path.read_text()))

    def test_the_matrix_is_current(self):
        self.assertEqual(tool().matrix(True), [])


class BuildChoice(unittest.TestCase):
    FIRMWARES = [{'version': '9.3.5', 'buildid': '13G36'}, {'version': '8.4.1', 'buildid': '12H321'},
                 {'version': '7.1.2', 'buildid': '11D257'}]

    def choose(self, chip, recipe=None, firmwares=None):
        firmware, rule = tool().choose_build(firmwares or self.FIRMWARES, chip, recipe)
        return firmware['buildid'], rule

    def test_the_chips_reference_version_wins(self):
        self.assertEqual(self.choose({'reference_version': '8.4.1'}, '11D257'), ('12H321', 'chip-reference'))

    def test_without_it_the_newest_of_that_major_version(self):
        firmwares = [{'version': '26.0', 'buildid': 'C'}, {'version': '18.6.2', 'buildid': 'B'},
                     {'version': '18.1', 'buildid': 'A'}]
        self.assertEqual(self.choose({'reference_version': '18.7.10'}, firmwares=firmwares),
                         ('B', 'chip-reference-major'))

    def test_then_the_firmware_recipes_build(self):
        self.assertEqual(self.choose({}, '12H321'), ('12H321', 'firmware-recipe'))

    def test_otherwise_the_newest(self):
        self.assertEqual(self.choose({}), ('13G36', 'newest'))


class IdentityOnlyBoards(unittest.TestCase):
    """A board with no [kernel] is recognised, but nothing tries to build or install it."""

    def test_it_loads_and_matches_in_dfu(self):
        from orchard import devices
        adapter = devices.load('k93')
        self.assertTrue(adapter.matches_dfu({'chip': 0x8940, 'board': 0x04}))
        self.assertIsNone(adapter.DEVICETREE)
        self.assertFalse(adapter.INSTALL)

    def test_no_build_selects_it(self):
        from orchard.ram import boards_by_platform
        boards = boards_by_platform(ROOT)
        self.assertFalse(any('k93' in platform or 'd20' in platform for platform in boards.values()))
        self.assertIn('j71b', boards['apple-16k'])

    def test_asking_for_its_firmware_says_there_is_none(self):
        from orchard import hardware
        with self.assertRaisesRegex(ValueError, 'no firmware recipe'):
            hardware.firmware_path('k93')

    def test_install_says_why_not(self):
        from orchard import service
        adapter = mock.Mock(DEVICETREE=None, INSTALL=False, NAME='iPad 2 (Wi-Fi)')
        with mock.patch.object(service, 'choose', return_value=(adapter, {})):
            with tempfile.TemporaryDirectory() as directory, mock.patch.dict('os.environ', {'XDG_CACHE_HOME': directory}):
                with self.assertRaisesRegex(ValueError, 'has no devicetree yet'):
                    service.install()


if __name__ == '__main__':
    unittest.main()
