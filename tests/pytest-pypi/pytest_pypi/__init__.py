from __future__ import absolute_import
import os
import sys
PIPENV_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath('__init__.py')))))
PIPENV_PATCHED = os.sep.join([PIPENV_DIR, 'patched'])
PIPENV_VENDOR = os.sep.join([PIPENV_DIR, 'vendor'])
# Inject vendored directory into system path.
sys.path.insert(0, PIPENV_VENDOR)
# Inject patched directory into system path.
sys.path.insert(0, PIPENV_PATCHED)

import pytest

here = os.path.dirname(__file__)
version_file = os.path.join(here, "version.py")

with open(version_file) as f:
    code = compile(f.read(), version_file, 'exec')
    exec(code)

use_class_based_httpbin = pytest.mark.usefixtures("class_based_pypi")
use_class_based_httpbin_secure = pytest.mark.usefixtures("class_based_pypi_secure")
