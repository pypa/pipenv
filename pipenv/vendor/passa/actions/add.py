# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import itertools
import sys


def add_packages(packages=[], editables=[], project=None, dev=False, sync=False, clean=False):
    from passa.models.lockers import PinReuseLocker
    from passa.operations.lock import lock

    lines = list(itertools.chain(
        packages,
        ("-e {}".format(e) for e in editables),
    ))

    project = project
    for line in lines:
        try:
            project.add_line_to_pipfile(line, develop=dev)
        except (TypeError, ValueError) as e:
            print("Cannot add {line!r} to Pipfile: {error}".format(
                line=line, error=str(e),
            ), file=sys.stderr)
            return 2

    prev_lockfile = project.lockfile

    locker = PinReuseLocker(project)
    success = lock(locker)
    if not success:
        return 1

    project._p.write()
    project._l.write()
    print("Written to project at", project.root)

    if not sync:
        return

    from passa.models.synchronizers import Synchronizer
    from passa.operations.sync import sync

    lockfile_diff = project.difference_lockfile(prev_lockfile)
    default = any(lockfile_diff.default)
    develop = any(lockfile_diff.develop)

    syncer = Synchronizer(
        project, default=default, develop=develop,
        clean_unneeded=clean,
    )
    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)
