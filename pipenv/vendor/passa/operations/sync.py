# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals


def sync(syncer):
    print("Starting synchronization")
    installed, updated, cleaned = syncer.sync()
    if cleaned:
        print("Uninstalled: {}".format(", ".join(sorted(cleaned))))
    if installed:
        print("Installed: {}".format(", ".join(sorted(installed))))
    if updated:
        print("Updated: {}".format(", ".join(sorted(updated))))
    return True


def clean(cleaner):
    print("Cleaning")
    cleaned = cleaner.clean()
    if cleaned:
        print("Uninstalled: {}".format(", ".join(sorted(cleaned))))
    return True
