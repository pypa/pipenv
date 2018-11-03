import contextlib
import os
import tempfile


# The numbers are set arbitrarily in an effort to be as unique as possible.
# I chose 919347 since it sort of looks like "PIPENV". -- uranusjr
ERROR_CODES = {
    key: code
    for code, key in enumerate([
        "NO_ENSUREPIP",
        "NO_VENV",
        "PYTHON_TOO_OLD",
        "IN_VIRTUALENV",
    ], 91934701)
}

SCRIPT = '''

from __future__ import print_function

import os
import subprocess
import sys

if sys.version_info < (3, 6):
    sys.exit({ERROR_CODES[PYTHON_TOO_OLD]!r})

# HACK: venv is broken in a virtualenv-created environment, and we can't use
# it in this situation. virtualenv sets this non-standard attribute.
# See bpo-30811 and pypa/virtualenv#1095 for discussion on this.
try:
    sys.real_prefix
except AttributeError:
    pass
else:
    sys.exit({ERROR_CODES[IN_VIRTUALENV]!r})

try:
    import venv
except ImportError:
    sys.exit({ERROR_CODES[NO_VENV]!r})

try:
    import ensurepip
except ImportError:
    sys.exit({ERROR_CODES[NO_ENSUREPIP]!r})

class _EnvBuilder(venv.EnvBuilder):
    """Custom environment builder to ensure libraries are up-to-date.

    Also add some output to make the process more verbose, matching
    virtualenv's behavior.
    """
    def setup_python(self, context):
        super(_EnvBuilder, self).setup_python(context)
        print('New Python executable in', context.env_exe)

    def post_setup(self, context):
        print('Ensuring up-to-date setuptools, pip, and wheel...',
              end='', flush=True)
        returncode = subprocess.call([
            context.env_exe, '-m', 'pip', 'install',
            '--upgrade', '--disable-pip-version-check', '--quiet',
            'setuptools', 'pip', 'wheel',
        ])
        if returncode == 0:
            print('done')
        else:
            # If update fails, there should already be a nice error message
            # from pip present. Just carry on.
            print()

builder = _EnvBuilder(
    prompt={prompt!r},
    system_site_packages={system_site_packages!r},
    symlinks=(os.name != 'nt'),  # Copied from venv logic.
    with_pip=True,
)
builder.create({env_dir!r})
'''


@contextlib.contextmanager
def create_script(env_dir, prompt, system):
    script = SCRIPT.format(
        env_dir=str(env_dir),
        prompt=prompt,
        system_site_packages=bool(system),
        ERROR_CODES=ERROR_CODES,
    )

    # We can't use tempfile.TemporaryFile here because we need to pass the
    # script to another process (the docs say it's not guarenteed to work).
    fd, filename = tempfile.mkstemp(suffix=".py", text=True)
    with os.fdopen(fd, "w") as f:
        f.write(script)
    try:
        yield filename
    finally:
        try:
            os.unlink(filename)
        except Exception:
            pass
