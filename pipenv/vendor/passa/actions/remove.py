# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals


def remove(project=None, only="default", packages=[], clean=True):
    from passa.models.lockers import PinReuseLocker
    from passa.operations.lock import lock

    default = (only != "dev")
    develop = (only != "default")

    project = project
    project.remove_keys_from_pipfile(
        packages, default=default, develop=develop,
    )

    locker = PinReuseLocker(project)
    success = lock(locker)
    if not success:
        return 1

    project._p.write()
    project._l.write()
    print("Written to project at", project.root)

    if not clean:
        return

    from passa.models.synchronizers import Cleaner
    from passa.operations.sync import clean

    cleaner = Cleaner(project, default=True, develop=True)
    success = clean(cleaner)
    if not success:
        return 1

    print("Cleaned project at", project.root)
