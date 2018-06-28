import contextlib
import os

from pipenv.patched import crayons
from pipenv.vendor import blindspin, click

from pipenv.core import BAD_PACKAGES, project
from pipenv.environments import (
    PIPENV_COLORBLIND,
    PIPENV_DONT_LOAD_ENV,
    PIPENV_DOTENV_LOCATION,
    PIPENV_NOSPIN,
)
from pipenv.utils import proper_case


# Disable colors, for the color blind and others who do not prefer colors.
if PIPENV_COLORBLIND:
    crayons.disable()


# Disable spinner, for cleaner build logs (the unworthy).
if PIPENV_NOSPIN:
    @contextlib.contextmanager  # noqa: F811
    def spinner():
        yield
else:
    spinner = blindspin.spinner


def convert_deps_to_pip(deps, project=None, r=True, include_index=False):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one.
    """
    from pipenv._compat import NamedTemporaryFile
    from pipenv.vendor import requirementslib
    dependencies = []
    for dep_name, dep in deps.items():
        indexes = project.sources if hasattr(project, 'sources') else None
        new_dep = requirementslib.Requirement.from_pipfile(dep_name, dep)
        req = new_dep.as_line(
            sources=indexes if include_index else None
        ).strip()
        dependencies.append(req)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = NamedTemporaryFile(suffix='-requirements.txt', delete=False)
    f.write('\n'.join(dependencies).encode('utf-8'))
    f.close()
    return f.name


def load_dot_env():
    """Loads .env file into sys.environ.
    """
    if not PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        from pipenv.vendor import dotenv
        project_directory = project.project_directory or '.'
        denv = dotenv.find_dotenv(
            PIPENV_DOTENV_LOCATION or os.sep.join([project_directory, '.env'])
        )
        if os.path.isfile(denv):
            click.echo(
                crayons.normal(
                    'Loading .env environment variables...', bold=True
                ),
                err=True,
            )
        dotenv.load_dotenv(denv, override=True)


def import_from_code(path='.'):
    from pipreqs import pipreqs
    rs = []
    try:
        for r in pipreqs.get_all_imports(path):
            if r not in BAD_PACKAGES:
                rs.append(r)
        pkg_names = pipreqs.get_pkg_names(rs)
        return [proper_case(r) for r in pkg_names]
    except Exception:
        return []
