# -*- coding: utf-8 -*-
import os

OPEN_MIRRORS = [
    "https://pyup.io/aws/safety/free/",
]

API_VERSION = 'v1/'
SAFETY_ENDPOINT = 'safety/'
API_BASE_URL = 'https://pyup.io/api/' + API_VERSION + SAFETY_ENDPOINT

API_MIRRORS = [
    API_BASE_URL
]

REQUEST_TIMEOUT = 5

CACHE_FILE = os.path.join(
    os.path.expanduser("~"),
    ".safety",
    "cache.json"
)

# Colors
YELLOW = 'yellow'
RED = 'red'
GREEN = 'green'


# Exit codes
EXIT_CODE_OK = 0
EXIT_CODE_FAILURE = 1
EXIT_CODE_VULNERABILITIES_FOUND = 64
EXIT_CODE_INVALID_API_KEY = 65
EXIT_CODE_TOO_MANY_REQUESTS = 66
EXIT_CODE_UNABLE_TO_LOAD_LOCAL_VULNERABILITY_DB = 67
EXIT_CODE_UNABLE_TO_FETCH_VULNERABILITY_DB = 68
EXIT_CODE_MALFORMED_DB = 69
