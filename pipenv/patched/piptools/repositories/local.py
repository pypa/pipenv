# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from contextlib import contextmanager

from piptools.utils import as_tuple, key_from_req, make_install_requirement
from .base import BaseRepository
from pip9.utils.hashes import FAVORITE_HASH


def ireq_satisfied_by_existing_pin(ireq, existing_pin):
    """
    Return True if the given InstallationRequirement is satisfied by the
    previously encountered version pin.
    """
    version = next(iter(existing_pin.req.specifier)).version
    return version in ireq.req.specifier


class LocalRequirementsRepository(BaseRepository):
    """
    The LocalRequirementsRepository proxied the _real_ repository by first
    checking if a requirement can be satisfied by existing pins (i.e. the
    result of a previous compile step).

    In effect, if a requirement can be satisfied with a version pinned in the
    requirements file, we prefer that version over the best match found in
    PyPI.  This keeps updates to the requirements.txt down to a minimum.
    """
    def __init__(self, existing_pins, proxied_repository):
        self.repository = proxied_repository
        self.existing_pins = existing_pins

    @property
    def finder(self):
        return self.repository.finder

    @property
    def session(self):
        return self.repository.session

    @property
    def DEFAULT_INDEX_URL(self):
        return self.repository.DEFAULT_INDEX_URL

    def clear_caches(self):
        self.repository.clear_caches()

    def freshen_build_caches(self):
        self.repository.freshen_build_caches()

    def find_best_match(self, ireq, prereleases=None):
        key = key_from_req(ireq.req)
        existing_pin = self.existing_pins.get(key)
        if existing_pin and ireq_satisfied_by_existing_pin(ireq, existing_pin):
            project, version, _ = as_tuple(existing_pin)
            return make_install_requirement(
                project, version, ireq.extras, constraint=ireq.constraint
            )
        else:
            return self.repository.find_best_match(ireq, prereleases)

    def get_dependencies(self, ireq):
        return self.repository.get_dependencies(ireq)

    def get_hashes(self, ireq):
        key = key_from_req(ireq.req)
        existing_pin = self.existing_pins.get(key)
        if existing_pin and ireq_satisfied_by_existing_pin(ireq, existing_pin):
            hashes = existing_pin.options.get('hashes', {})
            hexdigests = hashes.get(FAVORITE_HASH)
            if hexdigests:
                return {
                    ':'.join([FAVORITE_HASH, hexdigest])
                    for hexdigest in hexdigests
                }
        return self.repository.get_hashes(ireq)

    @contextmanager
    def allow_all_wheels(self):
        with self.repository.allow_all_wheels():
            yield
