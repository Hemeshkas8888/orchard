"""How a device gets from DFU into a boot chain: which tool runs, and with what.

A boot method (methods.toml) is the chain that runs afterwards; an entry is how it
is reached. Several entries can reach one method. How to run a tool stays in code,
because device data updates on its own and must not choose what gets executed.
Which entry suits a board isn't established yet, so nothing is refused by chip or host.
"""
from dataclasses import dataclass
import os

DEFAULT = 'palera1n'


@dataclass(frozen=True)
class Entry:
    tool: str
    method: str
    arguments: tuple
    # Whether to reset the USB port if the device doesn't return after checkm8 (apple/replug.py).
    replug: bool

    def argv(self, executable, image):
        return [executable, *self.arguments, str(image)]


ENTRIES = {
    'palera1n': Entry('palera1n', 'checkm8-pongo', ('-p', '-k'), True),
    # Arguments from thisiscamk's J72 boot (orchard#59), the only measured use so far.
    'checkra1n': Entry('checkra1n', 'checkm8-pongo', ('-E', '-p', '-v', '-n', '-k'), False),
}


def select(described=None):
    """The entry to use: --via (ORCHARD_VIA), else the board's preference, else the default."""
    requested = os.environ.get('ORCHARD_VIA')
    if requested:
        if requested not in ENTRIES:
            raise ValueError(f'Unknown entry {requested}; this Orchard has {", ".join(sorted(ENTRIES))}')
        return requested
    preferred = (described or {}).get('boot', {}).get('entries', [])
    return next((name for name in preferred if name in ENTRIES), DEFAULT)
