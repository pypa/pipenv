# -*- coding: utf-8 -*-
import os

OPEN_MIRRORS = [
    "https://raw.githubusercontent.com/pyupio/safety-db/master/data/",
]

API_MIRRORS = [
    "https://pyup.io/api/v1/safety/"
]

REQUEST_TIMEOUT = 5

CACHE_VALID_SECONDS = 60 * 60 * 2  # 2 hours

CACHE_LICENSES_VALID_SECONDS = 60 * 60 * 24 * 7  # one week

CACHE_FILE = os.path.join(
    os.path.expanduser("~"),
    ".safety",
    "cache.json"
)
