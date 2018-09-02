"""
certs.py
~~~~~~~~

This module returns the preferred default CA certificate bundle.

If you are packaging pytest-httpbin, e.g., for a Linux distribution or a
managed environment, you can change the definition of where() to return a
separately packaged CA bundle.
"""

import os.path


def where():
    """Return the preferred certificate bundle."""
    # vendored bundle inside Requests
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), 'certs', 'cacert.pem')

if __name__ == '__main__':
    print(where())
