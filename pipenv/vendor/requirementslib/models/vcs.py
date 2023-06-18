import importlib
import os
import sys
from typing import Any, Optional, Tuple

from pipenv.patched.pip._internal.utils.temp_dir import global_tempdir_manager
from pipenv.patched.pip._internal.vcs.versioncontrol import VcsSupport
from pipenv.patched.pip._vendor.pyparsing.core import cached_property
from pipenv.vendor.pydantic import BaseModel, Field

from .common import ReqLibBaseModel
from .url import URI


class VCSRepository(ReqLibBaseModel):
    url: str
    name: str
    checkout_directory: str
    vcs_type: str
    parsed_url: Optional[URI] = Field(default_factory=None)
    subdirectory: Optional[str] = None
    commit_sha: Optional[str] = None
    ref: Optional[str] = None
    repo_backend: Any = None
    clone_log: Optional[str] = None
    DEFAULT_RUN_ARGS: Optional[Any] = None

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        self.parsed_url = self.get_parsed_url()
        self.repo_backend = self.get_repo_backend()

    def get_parsed_url(self) -> URI:
        return URI.parse(self.url)

    def get_repo_backend(self):
        if self.DEFAULT_RUN_ARGS is None:
            default_run_args = self.monkeypatch_pip()
        else:
            default_run_args = self.DEFAULT_RUN_ARGS

        VCS_SUPPORT = VcsSupport()
        backend = VCS_SUPPORT.get_backend(self.vcs_type)
        if backend.run_command.__func__.__defaults__ != default_run_args:
            backend.run_command.__func__.__defaults__ = default_run_args
        return backend

    @property
    def is_local(self) -> bool:
        url = self.url
        if "+" in url:
            url = url.split("+")[1]
        return url.startswith("file")

    def obtain(self, verbosity=1) -> None:
        if os.path.exists(
            self.checkout_directory
        ) and not self.repo_backend.is_repository_directory(self.checkout_directory):
            self.repo_backend.unpack(self.checkout_directory)
        elif not os.path.exists(self.checkout_directory):
            self.repo_backend.obtain(self.checkout_directory, self.parsed_url, verbosity)
        else:
            if self.ref:
                self.checkout_ref(self.ref)
        if not self.commit_sha:
            self.commit_sha = self.commit_hash

    def checkout_ref(self, ref: str) -> None:
        rev_opts = self.repo_backend.make_rev_options(ref)
        if not any(
            [
                self.repo_backend.is_commit_id_equal(self.checkout_directory, ref),
                self.repo_backend.is_commit_id_equal(self.checkout_directory, rev_opts),
                self.is_local,
            ]
        ):
            self.update(ref)

    def update(self, ref: str) -> None:
        target_ref = self.repo_backend.make_rev_options(ref)
        self.repo_backend.update(self.checkout_directory, self.url, target_ref)
        self.commit_sha = self.commit_hash

    @cached_property
    def commit_hash(self) -> str:
        return self.repo_backend.get_revision(self.checkout_directory)

    @classmethod
    def monkeypatch_pip(cls) -> Tuple[Any, ...]:
        target_module = VcsSupport.__module__
        pip_vcs = importlib.import_module(target_module)
        run_command_defaults = pip_vcs.VersionControl.run_command.__func__.__defaults__
        new_defaults = [False] + list(run_command_defaults)[1:]
        new_defaults = tuple(new_defaults)
        pip_vcs.VersionControl.run_command.__func__.__defaults__ = new_defaults
        sys.modules[target_module] = pip_vcs
        cls.DEFAULT_RUN_ARGS = new_defaults
        return new_defaults
