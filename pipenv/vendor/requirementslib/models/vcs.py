# -*- coding=utf-8 -*-
import attr
from pip_shims import VcsSupport
import os


VCS_SUPPORT = VcsSupport()


@attr.s
class VCSRepository(object):
    url = attr.ib()
    name = attr.ib()
    checkout_directory = attr.ib()
    vcs_type = attr.ib()
    commit_sha = attr.ib(default=None)
    ref = attr.ib(default=None)
    repo_instance = attr.ib()

    @repo_instance.default
    def get_repo_instance(self):
        backend = VCS_SUPPORT._registry.get(self.vcs_type)
        return backend(url=self.url)

    def obtain(self):
        if not os.path.exists(self.checkout_directory):
            self.repo_instance.obtain(self.checkout_directory)
        if self.ref:
            self.checkout_ref(self.ref)
            self.commit_sha = self.get_commit_hash(self.ref)
        else:
            self.ref = self.repo_instance.default_arg_rev
            if not self.commit_sha:
                self.commit_sha = self.get_commit_hash()

    def checkout_ref(self, ref):
        target_rev = self.repo_instance.make_rev_options(ref)
        if not self.repo_instance.is_commit_id_equal(
            self.checkout_directory, self.get_commit_hash(ref)
        ) and not self.repo_instance.is_commit_id_equal(self.checkout_directory, ref):
            self.repo_instance.switch(self.checkout_directory, self.url, target_rev)

    def update(self, ref):
        target_rev = self.repo_instance.make_rev_options(ref)
        self.repo_instance.update(self.checkout_directory, target_rev)

    def get_commit_hash(self, ref=None):
        return self.repo_instance.get_revision(self.checkout_directory)
