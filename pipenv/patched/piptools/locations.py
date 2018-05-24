import os
from shutil import rmtree

from .click import secho
# Patch by vphilippon 2017-11-22: Use pipenv cache path.
# from ._compat import user_cache_dir
from pipenv.environments import PIPENV_CACHE_DIR

# The user_cache_dir helper comes straight from pipenv.patched.notpip itself
# CACHE_DIR = user_cache_dir(os.path.join('pip-tools'))
CACHE_DIR = PIPENV_CACHE_DIR

# NOTE
# We used to store the cache dir under ~/.pip-tools, which is not the
# preferred place to store caches for any platform.  This has been addressed
# in pip-tools==1.0.5, but to be good citizens, we point this out explicitly
# to the user when this directory is still found.
LEGACY_CACHE_DIR = os.path.expanduser('~/.pip-tools')

if os.path.exists(LEGACY_CACHE_DIR):
    secho('Removing old cache dir {} (new cache dir is {})'.format(LEGACY_CACHE_DIR, CACHE_DIR), fg='yellow')
    rmtree(LEGACY_CACHE_DIR)
