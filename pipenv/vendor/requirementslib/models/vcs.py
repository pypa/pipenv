# -*- coding=utf-8 -*-
import attr
import os
import pip_shims



@attr.s
class VCSRepository(object):
    url = attr.ib()
    name = attr.ib()
    checkout_directory = attr.ib()
    vcs_type = attr.ib()
    subdirectory = attr.ib(default=None)
    commit_sha = attr.ib(default=None)
    ref = attr.ib(default=None)
    repo_instance = attr.ib()

    @repo_instance.default
    def get_repo_instance(self):
        from pip_shims import VcsSupport
        VCS_SUPPORT = VcsSupport()
        backend = VCS_SUPPORT._registry.get(self.vcs_type)
        return backend(url=self.url)

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
