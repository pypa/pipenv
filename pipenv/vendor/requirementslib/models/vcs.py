# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import attr
import importlib
import os
import pip_shims
import six
import sys


@attr.s(hash=True)
class VCSRepository(object):
    DEFAULT_RUN_ARGS = None

    url = attr.ib()
    name = attr.ib()
    checkout_directory = attr.ib()
    vcs_type = attr.ib()
    subdirectory = attr.ib(default=None)
    commit_sha = attr.ib(default=None)
    ref = attr.ib(default=None)
    repo_instance = attr.ib()
    clone_log = attr.ib(default=None)

    @repo_instance.default
    def get_repo_instance(self):
        if self.DEFAULT_RUN_ARGS is None:
            default_run_args = self.monkeypatch_pip()
        else:
            default_run_args = self.DEFAULT_RUN_ARGS
        from pip_shims.shims import VcsSupport
        VCS_SUPPORT = VcsSupport()
        backend = VCS_SUPPORT._registry.get(self.vcs_type)
        repo = backend(url=self.url)
        if repo.run_command.__func__.__defaults__ != default_run_args:
            repo.run_command.__func__.__defaults__ = default_run_args
        return repo

    @property
    def is_local(self):
        url = self.url
        if '+' in url:
            url = url.split('+')[1]
        return url.startswith("file")

    def obtain(self):
        if (os.path.exists(self.checkout_directory) and not
                self.repo_instance.is_repository_directory(self.checkout_directory)):
            self.repo_instance.unpack(self.checkout_directory)
        elif not os.path.exists(self.checkout_directory):
            self.repo_instance.obtain(self.checkout_directory)
        else:
            if self.ref:
                self.checkout_ref(self.ref)
        if not self.commit_sha:
            self.commit_sha = self.get_commit_hash()

    def checkout_ref(self, ref):
        if not self.repo_instance.is_commit_id_equal(
            self.checkout_directory, self.get_commit_hash()
        ) and not self.repo_instance.is_commit_id_equal(self.checkout_directory, ref):
            if not self.is_local:
                self.update(ref)

    def update(self, ref):
        target_ref = self.repo_instance.make_rev_options(ref)
        if pip_shims.parse_version(pip_shims.pip_version) > pip_shims.parse_version("18.0"):
            self.repo_instance.update(self.checkout_directory, self.url, target_ref)
        else:
            self.repo_instance.update(self.checkout_directory, target_ref)
        self.commit_sha = self.get_commit_hash()

    def get_commit_hash(self, ref=None):
        return self.repo_instance.get_revision(self.checkout_directory)

    @classmethod
    def monkeypatch_pip(cls):
        target_module = pip_shims.shims.VcsSupport.__module__
        pip_vcs = importlib.import_module(target_module)
        run_command_defaults = pip_vcs.VersionControl.run_command.__defaults__
        # set the default to not write stdout, the first option sets this value
        new_defaults = [False,] + list(run_command_defaults)[1:]
        new_defaults = tuple(new_defaults)
        if six.PY3:
            try:
                pip_vcs.VersionControl.run_command.__defaults__ = new_defaults
            except AttributeError:
                pip_vcs.VersionControl.run_command.__func__.__defaults__ = new_defaults
        else:
            pip_vcs.VersionControl.run_command.__func__.__defaults__ = new_defaults
        sys.modules[target_module] = pip_vcs
        cls.DEFAULT_RUN_ARGS = new_defaults
        return new_defaults
