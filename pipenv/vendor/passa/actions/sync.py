# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals


def sync(project=None, dev=False, clean=True):
    from passa.models.synchronizers import Synchronizer
    from passa.operations.sync import sync

    project = project
    syncer = Synchronizer(
        project, default=True, develop=dev,
        clean_unneeded=clean,
    )

    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)
