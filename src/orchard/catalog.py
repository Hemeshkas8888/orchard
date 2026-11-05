"""The device catalog published from orchard's main branch, cached locally.

A published orchard (a nightly, a release, an installed core) reads device data
from here, so data updates don't need a CLI update. A checkout reads its own
files instead (hardware.data_root). The schema is the only contract: this module
fetches the newest catalog of the major version this code understands.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
import urllib.request

from .cache import shared_cache_root

SCHEMA = 1
URL = f'https://github.com/OrchardLinux/orchard/releases/download/catalog-v{SCHEMA}/catalog.json'
CHECK_EVERY = 3600  # seconds; a bad catalog is fixed by publishing, so don't wait long
TIMEOUT = 10
KEEP = 2
HEADERS = {'User-Agent': 'orchard-catalog'}


def _store():
    return shared_cache_root() / 'catalog'


def _read(url, limit):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'{url} is larger than expected')
    return data


def _unpack(data, destination):
    """Regular files and directories only, inside the destination."""
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.catalog-') as partial:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            for member in archive.getmembers():
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f'Unexpected catalog entry {member.name}')
            archive.extractall(partial, filter='data')
        try:
            os.replace(partial, destination)
        except OSError:  # another command unpacked the same catalog first
            if not destination.is_dir():
                raise
        else:
            Path(partial).mkdir()  # for the TemporaryDirectory's own cleanup


def _fetch(url):
    """Fetch the newest catalog into the store; returns its pointer."""
    pointer = json.loads(_read(url, 1 << 16))
    if pointer['schema'] != SCHEMA:
        raise ValueError(f'Catalog schema {pointer["schema"]}; this orchard reads {SCHEMA}')
    digest = pointer['sha256']
    if len(digest) != 64 or set(digest) - set('0123456789abcdef'):
        raise ValueError('Invalid catalog digest')
    destination = _store() / digest
    if not destination.is_dir():
        data = _read(url.rsplit('/', 1)[0] + '/' + pointer['file'], pointer['bytes'])
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Catalog does not match its digest')
        _unpack(data, destination)
    return pointer


def _write_pointer(pointer):
    path = _store() / 'current.json'
    partial = path.with_name(f'.current-{os.getpid()}')
    partial.write_text(json.dumps(pointer))
    os.replace(partial, path)


def _prune(current):
    entries = [path for path in _store().iterdir() if path.is_dir() and not path.name.startswith('.')]
    entries.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in [path for path in entries if path.name != current][KEEP - 1:]:
        shutil.rmtree(path, ignore_errors=True)


def current():
    """{'path': directory, **pointer} of the newest catalog we can get, or None.

    Checks at most once per CHECK_EVERY; without network, the cached one.
    """
    store = _store()
    store.mkdir(parents=True, exist_ok=True)
    checked = store / 'checked'
    try:
        pointer = json.loads((store / 'current.json').read_text())
    except (OSError, ValueError):
        pointer = None
    if pointer is not None and not (store / pointer['sha256']).is_dir():
        pointer = None
    fresh = checked.exists() and time.time() - checked.stat().st_mtime < CHECK_EVERY
    if pointer is None or not fresh:
        checked.touch()
        try:
            pointer = _fetch(os.environ.get('ORCHARD_CATALOG_URL', URL))
        except (OSError, ValueError, KeyError, tarfile.TarError):
            pass  # A cached catalog keeps working; a caller reports if there is none.
        else:
            _write_pointer(pointer)
            _prune(pointer['sha256'])
    return None if pointer is None else {**pointer, 'path': store / pointer['sha256']}
