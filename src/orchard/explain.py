"""What a build ran, as plain commands: the record behind `orchard build --explain`.

Every recipe orchard runs goes through build.command, which reports it here.
A cache entry keeps the commands that produced it (COMMANDS, inside the
entry), so a build that reuses the entry still lists how it was made. Steps
that are not a command of their own (orchard preparing a patched kernel tree
in its cache) are notes. The script marks what does not yet run without
orchard; docs/platforms-and-builds.md, "Projects, producers and boot", is the
plan for closing those gaps.
"""
import json
import shlex
import sys
from pathlib import Path

COMMANDS = 'commands.json'  # inside a cache entry: how it was produced

_build = None    # the build being recorded: a list of steps, or None
_entries = []    # cache entries being produced, innermost last: (stage, steps)


def start():
    global _build
    _build = []


def stop():
    global _build
    steps, _build = _build, None
    return steps or []


def _add(step):
    if _build is not None:
        _build.append(step)
    for _, steps in _entries:
        steps.append(step)


def command(argv):
    _add({'run': [str(a) for a in argv]})


def note(text):
    _add({'note': text})


def producing(stage):
    """Collect the commands that produce one cache entry into STAGE/COMMANDS."""
    class Entry:
        def __enter__(self):
            _entries.append((Path(stage), []))

        def __exit__(self, kind, *_):
            path, steps = _entries.pop()
            if kind is None:
                # Paths inside the temporary stage are the entry's own: name them by the entry.
                (path / COMMANDS).write_text(json.dumps(
                    [_rewrite(step, str(path), '$ENTRY') for step in steps], indent=2) + '\n')
    return Entry()


def reused(name, target):
    """A cache hit: the commands that once produced TARGET, or a note that none were recorded."""
    record = Path(target) / COMMANDS
    if not record.is_file():
        note(f'{name}: reused {target}, built before orchard recorded commands')
        return
    note(f'{name}: reused from the cache ({target}); it was produced by:')
    for step in json.loads(record.read_text()):
        _add(_rewrite(step, '$ENTRY', str(target)))


def _rewrite(step, old, new):
    if 'run' in step:
        return {'run': [a.replace(old, new) for a in step['run']]}
    return {'note': step['note'].replace(old, new)}


def _standalone(argv):
    """Why ARGV does not run without orchard yet, or None."""
    if len(argv) > 2 and argv[1] == '-m' and argv[2].startswith('orchard.'):
        return f'runs orchard\'s Python module {argv[2]}'
    if '--work-dir' in argv or any('/kernel-work/' in a for a in argv):
        return 'builds in orchard\'s kernel tree; standalone: kernel/build BOARD --kernel-tree DIR'
    return None


def script(steps, *, title):
    """STEPS as a shell script; the Python orchard ran with is named PYTHON."""
    lines = ['#!/bin/sh', f'# {title}', '# What orchard ran, in order (orchard build writes this; --explain prints it).',
             '# Lines marked "not standalone yet" still need orchard; everything else runs by path.',
             '# Paths are as they were: temporary directories are gone after the build.',
             f'PYTHON=${{PYTHON:-python3}}  # orchard ran {sys.executable}', 'set -eu', '']
    for step in steps:
        if 'note' in step:
            lines.extend('# ' + line for line in step['note'].splitlines())
            continue
        argv = ['"$PYTHON"' if a == sys.executable else shlex.quote(a) for a in step['run']]
        reason = _standalone(step['run'])
        if reason:
            lines.append(f'# not standalone yet: {reason}')
        lines.append(' '.join(argv))
    return '\n'.join(lines) + '\n'
