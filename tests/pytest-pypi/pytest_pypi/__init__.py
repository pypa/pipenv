import os

import pytest


here = os.path.dirname(__file__)
version_file = os.path.join(here, "version.py")

with open(version_file) as f:
    code = compile(f.read(), version_file, 'exec')
    exec(code)

use_class_based_httpbin = pytest.mark.usefixtures("class_based_pypi")
use_class_based_httpbin_secure = pytest.mark.usefixtures("class_based_pypi_secure")
