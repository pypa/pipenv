import sys

import pytest

from pipenv.vendor import pathlib2 as pathlib


@pytest.mark.install
@pytest.mark.update
@pytest.mark.graph
@pytest.mark.xfail(strict=True, reason='expected as reported in #2179')
def test_upgrade_gh2179(PipenvInstance, pypi):
    """Ensure upgrade gives a newer version than before.

    https://github.com/pypa/pipenv/issues/2179
    """
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        # Install an old version of requests.
        c = p.pipenv('install requests==2.14.0')
        assert c.return_code == 0

        # Ensure the version is correct (old).
        pipfile_content = pathlib.Path('Pipfile').read_text(encoding='utf-8')
        assert 'requests = "==2.14.0"' in pipfile_content

        # Rewrite version to "*" to get the latest version.
        pipfile_content = pipfile_content.replace('==2.14.0', '*', 1)
        pathlib.Path('Pipfile').write_text(pipfile_content, encoding='utf-8')

        # Ensure --outdated reports correctly.
        c = p.pipenv('update --outdated')
        assert c.return_code == 1   # Errors if there are outdated packages.
        assert "'==2.14.0' installed, '==2.18.4' available." in c.out

        # Try to upgrade.
        c = p.pipenv('update requests')
        assert c.return_code == 0

        # Ensure requests is actually upgraded.
        # FIXME: This fails. requests will not be updated, staying at 2.14.0.
        c = p.pipenv('graph')
        assert c.return_code == 0
        assert 'requests==2.18.4' in c.out
