# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import sys


def upgrade(project=None, strategy="only-if-needed", sync=True, packages=[]):
    from passa.models.lockers import EagerUpgradeLocker, PinReuseLocker
    from passa.operations.lock import lock

    for package in packages:
        if not project.contains_key_in_pipfile(package):
            print("{package!r} not found in Pipfile".format(
                package=package,
            ), file=sys.stderr)
            return 2

    project.remove_keys_from_lockfile(packages)

    prev_lockfile = project.lockfile

    if strategy == "eager":
        locker = EagerUpgradeLocker(project, packages)
    else:
        locker = PinReuseLocker(project)
    success = lock(locker)
    if not success:
        return 1

    project._l.write()
    print("Written to project at", project.root)

    if not sync:
        return

    from passa.operations.sync import sync
    from passa.models.synchronizers import Synchronizer

    lockfile_diff = project.difference_lockfile(prev_lockfile)
    default = bool(any(lockfile_diff.default))
    develop = bool(any(lockfile_diff.develop))

    syncer = Synchronizer(
        project, default=default, develop=develop,
        clean_unneeded=False,
    )
    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)
