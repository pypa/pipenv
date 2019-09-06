# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import os

import pytest

from pipenv._compat import Path


# This module is run only on Windows.
pytestmark = pytest.mark.skipif(os.name != 'nt', reason="only relevant on windows")


@pytest.mark.project
def test_case_changes_windows(PipenvInstance):
    """Test project matching for case changes on Windows.
    """
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('install pytz')
        assert c.return_code == 0

        # Canonical venv location.
        c = p.pipenv('--venv')
        assert c.return_code == 0
        virtualenv_location = c.out.strip()

        # Dance around to change the casing of the project directory.
        target = p.path.upper()
        if target == p.path:
            target = p.path.lower()
        os.chdir('..')
        os.chdir(target)
        assert os.path.abspath(os.curdir) != p.path

        # Ensure the incorrectly-cased project can find the correct venv.
        c = p.pipenv('--venv')
        assert c.return_code == 0
        assert c.out.strip().lower() == virtualenv_location.lower()


@pytest.mark.files
def test_local_path_windows(PipenvInstance):
    whl = (
        Path(__file__).parent.parent
        .joinpath('pypi', 'six', 'six-1.11.0-py2.py3-none-any.whl')
    )
    try:
        whl = whl.resolve()
    except OSError:
        whl = whl.absolute()
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('install "{0}"'.format(whl))
        assert c.return_code == 0


@pytest.mark.files
def test_local_path_windows_forward_slash(PipenvInstance):
    whl = (
        Path(__file__).parent.parent
        .joinpath('pypi', 'six', 'six-1.11.0-py2.py3-none-any.whl')
    )
    try:
        whl = whl.resolve()
    except OSError:
        whl = whl.absolute()
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('install "{0}"'.format(whl.as_posix()))
        assert c.return_code == 0


@pytest.mark.cli
def test_pipenv_clean_windows(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('install requests')
        assert c.return_code == 0
        c = p.pipenv('run pip install click')
        assert c.return_code == 0

        c = p.pipenv('clean --dry-run')
        assert c.return_code == 0
        assert 'click' in c.out.strip()
