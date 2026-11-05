"""The one way to read device data: descriptors, features, boot methods, firmware recipes, loaders.

Nothing else opens devices/, methods.toml or features.toml. ROOT says where they
are; `root` selects another checkout's data, for a build against another branch.
"""
import json
from pathlib import Path
import re
import subprocess
import tomllib

# The repository root: devices/, kernel/, boot/ and schemas/ sit beside src/.
ROOT = Path(__file__).resolve().parents[2]
# What this version of the code can do; data can name methods newer than this code.
IMPLEMENTED_METHODS = frozenset({'checkm8-pongo'})


def device_path(profile, root=None):
    if not isinstance(profile, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', profile):
        raise ValueError('Invalid hardware profile')
    path = Path(root or ROOT) / 'devices' / profile / 'device.toml'
    if not path.is_file() or path.is_symlink():
        raise ValueError('Hardware support is not installed for ' + profile)
    return path


def profiles(root=None):
    """Every device this hardware data describes."""
    devices = Path(root or ROOT) / 'devices'
    return sorted(path.parent.name for path in devices.glob('*/device.toml')
                  if not path.is_symlink() and not path.parent.is_symlink())


def features():
    """Feature names and display labels for device.toml [features], in display order."""
    return tomllib.loads((ROOT / 'features.toml').read_text())


def methods():
    """Boot methods a device.toml can list, and what each needs (methods.toml)."""
    return tomllib.loads((ROOT / 'methods.toml').read_text())


def device(profile, root=None):
    return tomllib.loads(device_path(profile, root).read_text())


def install_blockers(profile, described=None):
    """Why this Orchard can't install on a board: [] when it can.

    Installation follows from what a board has, so experimental boards get it
    as soon as it could work, even if other features don't work yet.
    """
    described = device(profile) if described is None else described
    blockers = []
    if 'kernel' not in described:
        blockers.append('it has no kernel or device tree yet')
    if not any(_method_usable(profile, name) for name in described.get('boot', {}).get('methods', [])):
        blockers.append('this Orchard has no boot method for it yet')
    if 'firmware' not in described:
        blockers.append('it has no firmware recipe yet')
    if described.get('features', {}).get('storage_write', 'missing') == 'missing':
        blockers.append('its internal storage cannot be written yet')
    return blockers


def _method_usable(profile, name):
    if name not in IMPLEMENTED_METHODS:
        return False
    if not methods()[name]['boot_json']:
        return True
    recipe = device_path(profile).parent / 'boot.json'
    return recipe.is_file() and name in json.loads(recipe.read_text())['methods']


def firmware_path(profile, root=None):
    descriptor = device_path(profile, root)
    described = device(profile, root)
    if 'firmware' not in described:
        raise ValueError(f'{profile} has no firmware recipe yet')
    name = described['firmware']['recipe']
    if ('\\' in name or ':' in name or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe firmware recipe resource')
    path = descriptor.parent
    for part in name.split('/'):
        path = path / part
        if path.is_symlink():
            raise ValueError('Linked firmware recipe refused')
    if not path.is_file():
        raise ValueError('Firmware recipe resource is missing')
    return path


def data_files(boards, root=None):
    """{path in a package: file} of the shared data and these boards' directories."""
    root = Path(root or ROOT)
    files = {'features.toml': root / 'features.toml', 'methods.toml': root / 'methods.toml'}
    for board in boards:
        directory = root / 'devices' / board
        if not (directory / 'device.toml').is_file():
            raise ValueError(f'orchard describes no device {board}')
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise ValueError(f'Device data must not contain links: {path}')
            if path.is_file() and '__pycache__' not in path.parts:
                files['devices/' + path.relative_to(root / 'devices').as_posix()] = path
    return files


def loader(profile):
    """The prebuilt Pongo and storage-capable m1n1 that start this device, if packaged.

    `orchard launch` needs only these two: m1n1 then reads the device's boot
    partition (docs/boot-contract.md), so launching depends on no distro and
    on nothing an install left on the host. Both are built once for every
    Apple device (boot/m1n1/build apple, boot/quiet/build-pongo.py); the
    published wheel carries them in loaders/, a source checkout has none and
    the CLI builds them instead. Returns {'pongo': Path, 'm1n1': Path} or None.
    """
    device_path(profile)
    root = ROOT / 'loaders'
    files = {'pongo': root / 'pongo.bin', 'm1n1': root / 'm1n1.bin'}
    if all(path.is_file() and not path.is_symlink() for path in files.values()):
        return files
    return None


def revision():
    """The orchard commit this checkout is at, for a release's build receipt.

    {'commit': SHA, 'modified': bool}; modified means the checkout differed
    from that commit, so the commit alone does not reproduce the build.
    """
    def git(*arguments):
        return subprocess.run(['git', '-C', str(ROOT), *arguments], capture_output=True,
                              text=True, check=True).stdout.strip()
    try:
        commit = git('rev-parse', 'HEAD')
        modified = bool(git('status', '--porcelain', '--untracked-files=no'))
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f'{ROOT} is not an orchard Git checkout; its revision is unknown') from error
    return {'commit': commit, 'modified': modified}
