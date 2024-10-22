import itertools
import os

import pytest

from pipenv import environments
from pipenv.utils.shell import temp_environ


@pytest.mark.environments
@pytest.mark.parametrize(
    "arg, prefix, use_negation",
    list(itertools.product(("ENABLE_SOMETHING",), ("FAKEPREFIX", None), (True, False))),
)
def test_get_from_env(arg, prefix, use_negation):
    negated_arg = f"NO_{arg}"
    positive_var = arg
    negative_var = negated_arg
    if prefix:
        negative_var = f"{prefix}_{negative_var}"
        positive_var = f"{prefix}_{positive_var}"
    # set the positive first
    for var_to_set, opposite_var in ((arg, negated_arg), (negated_arg, arg)):
        os.environ.pop(var_to_set, None)
        os.environ.pop(opposite_var, None)
        with temp_environ():
            is_positive = var_to_set == arg
            is_negative = not is_positive
            envvar = positive_var if is_positive else negative_var
            os.environ[envvar] = "true"
            main_expected_value = True if is_positive else None
            if use_negation and not is_positive:
                main_expected_value = False
            # use negation means if the normal variable isn't set we will check
            # for the negated version
            negative_expected_value = True if is_negative else None
            if is_positive:
                assert (
                    environments.get_from_env(
                        var_to_set, prefix=prefix, check_for_negation=use_negation
                    )
                    is main_expected_value
                )
                assert (
                    environments.get_from_env(
                        opposite_var, prefix=prefix, check_for_negation=use_negation
                    )
                    is negative_expected_value
                )
            else:
                # var_to_set = negative version i.e. NO_xxxx
                # opposite_var = positive_version i.e. XXXX

                # get NO_BLAH -- expecting this to be True
                assert (
                    environments.get_from_env(
                        var_to_set, prefix=prefix, check_for_negation=use_negation
                    )
                    is negative_expected_value
                )
                # get BLAH -- expecting False if checking for negation
                # but otherwise should be None
                assert (
                    environments.get_from_env(
                        opposite_var, prefix=prefix, check_for_negation=use_negation
                    )
                    is main_expected_value
                )


@pytest.mark.environments
@pytest.mark.parametrize(
    "check_for_negation, default",
    list(itertools.product((True, False), (None, "default", 1))),
)
def test_get_from_env_default(check_for_negation, default):
    """When the desired env var does"""
    arg = "ENABLE_SOMETHING"
    prefix = "FAKEPREFIX"
    envvar = f"{prefix}_{arg}"
    negated_envvar = f"{prefix}_NO_{arg}"
    with temp_environ():
        os.environ.pop(envvar, None)
        os.environ.pop(negated_envvar, None)
        assert (
            environments.get_from_env(
                arg, prefix=prefix, check_for_negation=check_for_negation, default=default
            )
            == default
        )


def test_pipenv_venv_in_project_set_true(monkeypatch):
    monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "1")
    assert environments.Setting().PIPENV_VENV_IN_PROJECT is True


def test_pipenv_venv_in_project_set_false(monkeypatch):
    monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "0")
    assert environments.Setting().PIPENV_VENV_IN_PROJECT is False


def test_pipenv_venv_in_project_unset(monkeypatch):
    monkeypatch.delenv("PIPENV_VENV_IN_PROJECT", raising=False)
    assert environments.Setting().PIPENV_VENV_IN_PROJECT is None
