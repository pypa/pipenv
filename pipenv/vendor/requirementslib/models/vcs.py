# -*- coding=utf-8 -*-
import attr
from pip_shims import VcsSupport, parse_version, pip_version
import vistir
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

    @property
    def is_local(self):
        url = self.url
        if '+' in url:
            url = url.split('+')[1]
        return url.startswith("file")

    def obtain(self):
        if not os.path.exists(self.checkout_directory):
            self.repo_instance.obtain(self.checkout_directory)
        if self.ref:
            self.checkout_ref(self.ref)
            self.commit_sha = self.get_commit_hash(self.ref)
        else:
            if not self.commit_sha:
                self.commit_sha = self.get_commit_hash()

    def checkout_ref(self, ref):
        if not self.repo_instance.is_commit_id_equal(
            self.checkout_directory, self.get_commit_hash(ref)
        ) and not self.repo_instance.is_commit_id_equal(self.checkout_directory, ref):
            if not self.is_local:
                self.update(ref)

    def update(self, ref):
        target_ref = self.repo_instance.make_rev_options(ref)
        sha = self.repo_instance.get_revision_sha(self.checkout_directory, target_ref.arg_rev)
        target_rev = target_ref.make_new(sha)
        if parse_version(pip_version) > parse_version("18.0"):
            self.repo_instance.update(self.checkout_directory, self.url, target_ref)
        else:
            self.repo_instance.update(self.checkout_directory, target_ref)
        self.commit_hash = self.get_commit_hash(ref)

    def get_commit_hash(self, ref=None):
        if ref:
            target_ref = self.repo_instance.make_rev_options(ref)
            return self.repo_instance.get_revision_sha(self.checkout_directory, target_ref.arg_rev)
            # return self.repo_instance.get_revision(self.checkout_directory)
        return self.repo_instance.get_revision(self.checkout_directory)
