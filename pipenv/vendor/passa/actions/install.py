# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals


def install(project=None, check=True, dev=False, clean=True):
    from passa.models.lockers import BasicLocker
    from passa.operations.lock import lock

    project = project

    if not check or not project.is_synced():
        locker = BasicLocker(project)
        success = lock(locker)
        if not success:
            return 1
        project._l.write()
        print("Written to project at", project.root)

    from passa.models.synchronizers import Synchronizer
    from passa.operations.sync import sync

    syncer = Synchronizer(
        project, default=True, develop=dev,
        clean_unneeded=clean,
    )

    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)
