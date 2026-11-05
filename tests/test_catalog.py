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
# Every iPhone and iPad on palera1n's device list (https://palera.in).
PALERA1N = '''n71 n71m n66 n66m n69 n69u d10 d101 d11 d111 d20 d201 d21 d211 d22 d221
              j96 j97 j71s j71t j72s j72t j71b j72b j171 j172 j127 j128 j98a j99a
              j207 j208 j120 j121 j81 j82'''


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

    def test_palera1ns_boards_list_checkm8_pongo(self):
        for board in PALERA1N.split():
            with self.subTest(board=board):
                described = tomllib.loads((ROOT / 'devices' / board / 'device.toml').read_text())
                self.assertIn('checkm8-pongo', described['boot']['methods'])

    def test_the_matrix_is_current(self):
        self.assertEqual(tool().matrix(True), [])


class Urls(unittest.TestCase):
    def test_the_old_http_host_is_replaced(self):
        self.assertEqual(tool().secure('http://appldnld.apple.com/ios10.3.3/a.ipsw'),
                         'https://secure-appldnld.apple.com/ios10.3.3/a.ipsw')
        self.assertEqual(tool().secure('https://updates.cdn-apple.com/a.ipsw'), 'https://updates.cdn-apple.com/a.ipsw')


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
        from orchard import devices, service
        with mock.patch.object(service, 'choose', return_value=(devices.load('k93'), {})):
            with tempfile.TemporaryDirectory() as directory, mock.patch.dict('os.environ', {'XDG_CACHE_HOME': directory}):
                with self.assertRaisesRegex(ValueError, 'no kernel or device tree yet') as caught:
                    service.install()
        self.assertNotIn('RAM boot', str(caught.exception))


class InferredInstall(unittest.TestCase):
    def test_the_boards_with_every_requirement_can_install(self):
        from orchard import hardware
        boards = {path.parent.name for path in DESCRIPTORS if not hardware.install_blockers(path.parent.name)}
        self.assertEqual(boards, {'d10', 'd101', 'd11', 'd111', 'd221', 'j171', 'j172', 'j71b', 'j71t', 'j72b', 'j72t'})

    def test_the_matrix_agrees_with_the_cli(self):
        from orchard import hardware
        generate = tool()
        for path in DESCRIPTORS:
            with self.subTest(board=path.parent.name):
                described = tomllib.loads(path.read_text())
                self.assertEqual(generate.can_install(path.parent.name, described),
                                 not hardware.install_blockers(path.parent.name, described))

    def test_each_requirement_blocks_with_its_reason(self):
        from orchard import hardware
        whole = hardware.device('j71b')
        for section, reason in (('kernel', 'kernel'), ('boot', 'boot method'), ('firmware', 'firmware')):
            with self.subTest(section=section):
                described = {key: value for key, value in whole.items() if key != section}
                self.assertTrue(any(reason in text for text in hardware.install_blockers('j71b', described)))
        described = {**whole, 'features': {**whole['features'], 'storage_write': 'missing'}}
        self.assertEqual(hardware.install_blockers('j71b', described), ['its internal storage cannot be written yet'])

    def test_untested_storage_is_enough(self):
        from orchard import hardware
        described = hardware.device('j71b')
        described = {**described, 'features': {**described['features'], 'storage_write': 'untested'}}
        self.assertEqual(hardware.install_blockers('j71b', described), [])

    def test_a_method_orchard_does_not_implement_is_not_enough(self):
        from orchard import hardware
        described = hardware.device('j71b')
        described = {**described, 'boot': {'methods': ['custom-dfu-recovery']}}
        self.assertIn('this Orchard has no boot method for it yet', hardware.install_blockers('j71b', described))


if __name__ == '__main__':
    unittest.main()
