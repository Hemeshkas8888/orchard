"""Published kernels: a distribution build takes the nightly's kernel instead of compiling it.

A platform's source key is a hash of the files that decide its kernel: the
upstream lock, the series and every patch it applies, the config, the
toolchain recipes, the descriptor's build fields and KERNEL_PRODUCER. Anyone
with an orchard checkout computes it without a kernel tree. CI publishes the
key of each platform it built (kernel-keys.json, listed in SHA256SUMS); a
distribution build whose checkout gives the same key downloads that
platform's bundle, checks it against SHA256SUMS and uses its kernel. Any
other key, no network, or ORCHARD_KERNEL=local: the kernel is compiled as
before. The published kernel is CI's build of exactly this kernel state, not
a claim that a local compile gives the same bytes (CI installs the
toolchain natively, a local build runs it in its container).

  python -m orchard.published keys --output kernel-keys.json [PLATFORM ...]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

KEYS = 'kernel-keys.json'
SUMS = 'SHA256SUMS'
TAG = 'nightly'
BUNDLE_LIMIT = 2 * 1024 * 1024 * 1024


def source_inputs(hardware, platform):
    """What decides PLATFORM's compiled kernel, from the checkout's files alone."""
    from .build import KERNEL_PRODUCER, recipe_entries
    hardware = Path(hardware)
    def series(*args):
        return subprocess.check_output([sys.executable, str(hardware / 'kernel/series.py'), *args], text=True)
    described = json.loads(series('--platform', platform))
    patches = [str(Path(line).resolve().relative_to(hardware.resolve())) for line in series(platform).splitlines()]
    return {
        'platform': platform,
        'build': {key: described[key] for key in ('arch', 'image', 'dtbs')},
        'recipes': recipe_entries(hardware, [described['upstream'], described['series'], described['config'],
                                             'kernel/Containerfile', 'kernel/install-toolchain', *patches]),
        'producer': KERNEL_PRODUCER,
    }


def source_key(hardware, platform):
    return hashlib.sha256(json.dumps(source_inputs(hardware, platform), sort_keys=True).encode()).hexdigest()


def write_keys(hardware, platforms, output):
    keys = {'schema': 1, 'platforms': {platform: {'key': source_key(hardware, platform),
                                                  'bundle': f'{platform}-components.tar.gz'}
                                       for platform in platforms}}
    Path(output).write_text(json.dumps(keys, indent=2, sort_keys=True) + '\n')
    return keys


def _fetch(url, limit):
    from .http import open_url
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'{url} is larger than expected')
    return data


def _sums(text):
    rows = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            rows[parts[1].removeprefix('./')] = parts[0]
    return rows


def kernel(hardware, cache, platform, *, tag=TAG):
    """PLATFORM's published kernel directory for this checkout's source key, or None to compile."""
    if os.environ.get('ORCHARD_KERNEL') == 'local':
        return None
    from .build import RELEASES, cached_component, component_lock
    key = source_key(hardware, platform)
    components = Path(cache) / 'components-v2'
    name = f'kernel-published-{platform}'
    if not (components / name / key).is_dir():
        try:
            sums = _sums(_fetch(f'{RELEASES}/{tag}/{SUMS}', 1024 * 1024).decode())
            keys_data = _fetch(f'{RELEASES}/{tag}/{KEYS}', 1024 * 1024)
        except (OSError, ValueError) as error:
            print(f'No published {platform} kernel ({error}); compiling it', flush=True)
            return None
        if hashlib.sha256(keys_data).hexdigest() != sums.get(KEYS):
            print(f'The {tag} {KEYS} does not match its {SUMS}; compiling the kernel', flush=True)
            return None
        entry = json.loads(keys_data).get('platforms', {}).get(platform)
        if not entry or entry.get('key') != key:
            print(f'The {tag} {platform} kernel is of another kernel state; compiling it', flush=True)
            return None
        bundle, checksum = entry['bundle'], sums.get(entry['bundle'])
        if not checksum or '/' in bundle:
            return None
    def produce(stage):
        print(f'Using the {tag} {platform} kernel: its source key matches this checkout', flush=True)
        from .http import open_url
        with tempfile.TemporaryDirectory(prefix='published-', dir=stage.parent) as temporary:
            archive = Path(temporary) / bundle
            digest, size = hashlib.sha256(), 0
            with open_url(f'{RELEASES}/{tag}/{bundle}', timeout=300) as response, archive.open('wb') as out:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > BUNDLE_LIMIT:
                        raise ValueError(f'{bundle} is larger than expected')
                    digest.update(block)
                    out.write(block)
            if digest.hexdigest() != checksum:
                raise ValueError(f'{bundle} does not match {SUMS}')
            with tarfile.open(archive) as tar:
                members = [m for m in tar.getmembers() if m.name.startswith('components/kernel/')]
                for member in members:
                    if not (member.isfile() or member.isdir()) or '..' in Path(member.name).parts:
                        raise ValueError(f'{bundle}: unexpected member {member.name}')
                tar.extractall(Path(temporary) / 'x', members=members, filter='data')
            shutil.move(Path(temporary) / 'x/components/kernel', stage / 'kernel')
        (stage / 'published.json').write_text(json.dumps(
            {'tag': tag, 'bundle': bundle, 'sha256': checksum, 'source_key': key}, indent=2) + '\n')
    with component_lock(cache):
        return cached_component(components, name, lambda: key, produce) / 'kernel'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='action', required=True)
    keys = commands.add_parser('keys', help=f'write {KEYS} for the given (default: every arm64) platform')
    keys.add_argument('--output', type=Path, required=True)
    keys.add_argument('platform', nargs='*')
    args = parser.parse_args()
    from .hardware import ROOT
    from .image.platform import platforms
    print(json.dumps(write_keys(ROOT, args.platform or platforms(), args.output), indent=2))


if __name__ == '__main__':
    main()
