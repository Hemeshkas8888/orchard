"""What a distribution build gets from orchard, as one JSON file: the distribution contract's entry.

  python -m orchard.inputs --output inputs.json [--platform NAME ...] [--kernel-dir PLATFORM=DIR ...]

A distribution's build runs orchard's producers as commands from an orchard
snapshot (a checkout, the newest nightly's tooling, or a release's
orchard-source.tar.gz unpacked) with PYTHONPATH=SNAPSHOT/src, and imports none
of orchard's Python. This command resolves everything the distribution takes
finished: per platform its kernel bundle (Image.gz, every board's DTB,
modules; the nightly's when its source key matches, else built), its boards
and their DTBs, and the shared m1n1, Pongo and static tools, plus the
snapshot's revision. Paths point into orchard's cache and stay valid for the
build. The other producers of the contract (docs/distribution-contract.md)
take these paths as arguments.

Without --platform: every platform a distribution root serves (arm64).
"""
import argparse
import json
from pathlib import Path
import sys

SCHEMA = 1


def resolve(platforms=None, explicit=None, *, hardware=None, cache=None):
    """The inputs document for PLATFORMS (default: every arm64 platform)."""
    from .build import prepare_shared
    from .hardware import ROOT, revision
    from .image import platform
    hardware = Path(hardware or ROOT)
    explicit = explicit or {}
    known = platform.platforms(hardware)
    selected = list(platforms or known)
    unknown = sorted(set(selected) - set(known)) + sorted(set(explicit) - set(selected))
    if unknown:
        raise ValueError(f'Unknown or unselected platform {", ".join(unknown)}; known: {", ".join(known)}')
    shared = prepare_shared(hardware, cache)
    tools = Path(shared['tools'])
    try:
        orchard = revision()
    except ValueError:
        orchard = {'commit': None, 'modified': None}
    return {
        'schema': SCHEMA,
        'orchard': orchard,
        'platforms': {name: {'kernel': str(Path(explicit.get(name) or platform.kernel(name, hardware=hardware,
                                                                                         cache=cache)).resolve()),
                             'boards': platform.boards(name, hardware)}
                      for name in selected},
        'shared': {'m1n1': str(shared['loader']), 'pongo': str(shared['pongo']),
                   'tools': {name: str(tools / name) for name in
                             ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw')}},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output', type=Path, required=True, help='the JSON document to write')
    parser.add_argument('--platform', action='append', help='a platform to build for; repeat (default: every one)')
    parser.add_argument('--kernel-dir', action='append', default=[], metavar='PLATFORM=DIRECTORY',
                        help="a platform's staged kernel bundle instead of orchard's")
    args = parser.parse_args()
    explicit = {}
    for value in args.kernel_dir:
        name, separator, path = value.partition('=')
        if not separator:
            parser.error('--kernel-dir takes PLATFORM=DIRECTORY')
        explicit[name] = Path(path)
    try:
        document = resolve(args.platform, explicit)
    except ValueError as error:
        sys.exit(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    print(f'orchard inputs for {", ".join(document["platforms"])}: {args.output}')


if __name__ == '__main__':
    main()
