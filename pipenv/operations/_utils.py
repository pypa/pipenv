import contextlib

from pipenv.patched import crayons
from pipenv.vendor import blindspin

from pipenv.environments import (
    PIPENV_COLORBLIND,
    PIPENV_NOSPIN,
)


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
