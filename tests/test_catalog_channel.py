"""A published orchard downloads and caches device data; a checkout uses its own."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from orchard import catalog, hardware

ROOT = Path(__file__).resolve().parents[1]


def tool():
    loader = importlib.machinery.SourceFileLoader('catalog_generate', str(ROOT / 'tools/catalog/generate'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Channel(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.server = self.home / 'server'
        tool().publish(self.server, 'abc123')
        self.url = (self.server / 'catalog.json').as_uri()
        environment = {'ORCHARD_CACHE_DIR': str(self.home / 'cache'), 'ORCHARD_CATALOG_URL': self.url}
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def age_check(self):
        os.utime(catalog._store() / 'checked', (1, 1))

    def test_it_downloads_and_unpacks_what_a_cli_reads(self):
        latest = catalog.current()
        self.assertEqual(latest['commit'], 'abc123')
        self.assertTrue((latest['path'] / 'devices/j71b/device.toml').is_file())
        self.assertTrue((latest['path'] / 'devices/j71b/firmware.json').is_file())
        self.assertTrue((latest['path'] / 'devices/k93/boot.json').is_file())
        self.assertTrue((latest['path'] / 'methods.toml').is_file())
        self.assertFalse(list(latest['path'].rglob('README.md')))

    def test_the_hardware_boundary_reads_it(self):
        path = catalog.current()['path']
        self.assertEqual(hardware.device('k93', path)['device']['profile'], 'k93')
        self.assertIn('j71b', hardware.profiles(path))

    def test_a_cached_catalog_works_without_network(self):
        first = catalog.current()
        self.age_check()
        (self.server / 'catalog.json').unlink()
        self.assertEqual(catalog.current()['sha256'], first['sha256'])

    def test_nothing_cached_and_no_network_is_none(self):
        (self.server / 'catalog.json').unlink()
        self.assertIsNone(catalog.current())

    def test_a_catalog_that_does_not_match_its_digest_is_refused(self):
        first = catalog.current()
        pointer = json.loads((self.server / 'catalog.json').read_text())
        (self.server / 'catalog.json').write_text(json.dumps({**pointer, 'sha256': 'a' * 64}))
        self.age_check()
        self.assertEqual(catalog.current()['sha256'], first['sha256'])
        self.assertFalse((catalog._store() / ('a' * 64)).exists())

    def test_a_catalog_of_another_schema_is_ignored(self):
        first = catalog.current()
        pointer = json.loads((self.server / 'catalog.json').read_text())
        (self.server / 'catalog.json').write_text(json.dumps({**pointer, 'schema': 2, 'sha256': 'b' * 64}))
        self.age_check()
        self.assertEqual(catalog.current()['sha256'], first['sha256'])

    def test_a_link_in_the_archive_is_refused(self):
        archive = self.server / 'evil.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            link = tarfile.TarInfo('devices')
            link.type, link.linkname = tarfile.SYMTYPE, '/etc'
            output.addfile(link)
        import hashlib
        data = archive.read_bytes()
        pointer = {'schema': 1, 'file': archive.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (self.server / 'catalog.json').write_text(json.dumps(pointer))
        self.assertIsNone(catalog.current())

    def test_it_checks_at_most_once_an_hour(self):
        catalog.current()
        with mock.patch.object(catalog, '_fetch') as fetch:
            catalog.current()
            fetch.assert_not_called()
            self.age_check()
            fetch.return_value = json.loads((catalog._store() / 'current.json').read_text())
            catalog.current()
            fetch.assert_called_once()

    def test_publishing_the_same_data_gives_the_same_bytes(self):
        second = self.home / 'second'
        tool().publish(second, 'abc123')
        self.assertEqual((second / 'catalog.json').read_text(), (self.server / 'catalog.json').read_text())

    def test_the_tool_and_the_cli_agree_on_the_schema(self):
        self.assertEqual(tool().CATALOG_SCHEMA, catalog.SCHEMA)


class DataRoot(unittest.TestCase):
    def setUp(self):
        hardware.data_root.cache_clear()
        self.addCleanup(hardware.data_root.cache_clear)

    def test_a_checkout_uses_its_own_files(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('ORCHARD_DATA', None)
            self.assertEqual(hardware.data_root(), hardware.ROOT)

    def test_orchard_data_wins(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'ORCHARD_DATA': directory}):
            (Path(directory) / 'devices').mkdir()
            self.assertEqual(hardware.data_root(), Path(directory))

    def test_orchard_data_must_hold_devices(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'ORCHARD_DATA': directory}):
            with self.assertRaisesRegex(ValueError, 'no devices/'):
                hardware.data_root()

    def test_a_published_orchard_reads_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ):
            os.environ.pop('ORCHARD_DATA', None)
            path = Path(directory) / 'catalog/' / ('c' * 64)
            with mock.patch.object(hardware, 'published', return_value=True), \
                    mock.patch('orchard.catalog.current', return_value={'path': path}):
                self.assertEqual(hardware.data_root(), path)

    def test_without_catalog_a_clone_uses_its_commit(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('ORCHARD_DATA', None)
            with mock.patch.object(hardware, 'published', return_value=True), \
                    mock.patch('orchard.catalog.current', return_value=None):
                self.assertEqual(hardware.data_root(), hardware.ROOT)

    def test_a_core_with_neither_says_so(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ):
            os.environ.pop('ORCHARD_DATA', None)
            with mock.patch.object(hardware, 'ROOT', Path(directory)), \
                    mock.patch.object(hardware, 'published', return_value=True), \
                    mock.patch('orchard.catalog.current', return_value=None):
                with self.assertRaisesRegex(ValueError, 'connect to the network once'):
                    hardware.data_root()


if __name__ == '__main__':
    unittest.main()
