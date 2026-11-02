"""A distribution build takes the nightly's kernel when its source key matches this checkout."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from orchard import http, published  # noqa: E402
from orchard.hardware import ROOT  # noqa: E402


def bundle():
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for name, content in (('components/kernel/Image.gz', b'kernel'),
                              ('components/kernel/kernel.release', b'7.3.0-test\n'),
                              ('components/boot/busybox', b'not the kernel')):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return data.getvalue()


class PublishedKernel(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name)
        self.bundle = bundle()
        self.keys = json.dumps({'schema': 1, 'platforms': {'apple-16k': {
            'key': published.source_key(ROOT, 'apple-16k'), 'bundle': 'apple-16k-components.tar.gz'}}}).encode()
        self.fetched = []
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('ORCHARD_KERNEL', None)

    def release(self, keys=None, bundle=None):
        keys, bundle = keys or self.keys, bundle or self.bundle
        sums = (f'{hashlib.sha256(self.bundle).hexdigest()}  ./apple-16k-components.tar.gz\n'
                f'{hashlib.sha256(self.keys).hexdigest()}  ./kernel-keys.json\n').encode()
        files = {'SHA256SUMS': sums, 'kernel-keys.json': keys, 'apple-16k-components.tar.gz': bundle}
        def open_url(url, timeout=60):
            self.fetched.append(url.rsplit('/', 1)[1])
            return io.BytesIO(files[url.rsplit('/', 1)[1]])
        return mock.patch.object(http, 'open_url', side_effect=open_url)

    def kernel(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return published.kernel(ROOT, self.cache, 'apple-16k')

    def test_a_matching_key_uses_the_published_kernel_and_reuses_it(self):
        with self.release():
            directory = self.kernel()
        self.assertEqual((directory / 'Image.gz').read_bytes(), b'kernel')
        self.assertFalse((directory.parent / 'boot').exists())
        with self.release():
            self.assertEqual(self.kernel(), directory)
        self.assertEqual(self.fetched.count('apple-16k-components.tar.gz'), 1)

    def test_another_kernel_state_compiles(self):
        other = json.dumps({'schema': 1, 'platforms': {'apple-16k': {
            'key': '0' * 64, 'bundle': 'apple-16k-components.tar.gz'}}}).encode()
        self.keys = other
        with self.release():
            self.assertIsNone(self.kernel())
        self.assertNotIn('apple-16k-components.tar.gz', self.fetched)

    def test_keys_not_in_the_checksums_are_not_trusted(self):
        with self.release(keys=self.keys + b' '):
            self.assertIsNone(self.kernel())

    def test_a_tampered_bundle_is_refused(self):
        with self.release(bundle=self.bundle + b'x'), self.assertRaisesRegex(ValueError, 'does not match'):
            self.kernel()

    def test_local_or_offline_compiles(self):
        os.environ['ORCHARD_KERNEL'] = 'local'
        with self.release():
            self.assertIsNone(self.kernel())
        self.assertEqual(self.fetched, [])
        del os.environ['ORCHARD_KERNEL']
        with mock.patch.object(http, 'open_url', side_effect=OSError('offline')):
            self.assertIsNone(self.kernel())

    def test_the_key_follows_the_kernel_files_not_the_rest(self):
        inputs = published.source_inputs(ROOT, 'apple-16k')
        self.assertIn('kernel/configs/apple-16k/config', inputs['recipes'])
        self.assertTrue(any(name.startswith('kernel/patches/') for name in inputs['recipes']))
        self.assertFalse(any(name.startswith(('devices/', 'docs/', 'src/')) for name in inputs['recipes']))


if __name__ == '__main__':
    unittest.main()
