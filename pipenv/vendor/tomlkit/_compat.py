import sys

from typing import Any
from typing import List
from typing import Optional


PY38 = sys.version_info >= (3, 8)


def decode(string: Any, encodings: Optional[List[str]] = None):
    if not isinstance(string, bytes):
        return string

    encodings = encodings or ["utf-8", "latin1", "ascii"]

    for encoding in encodings:
        try:
            return string.decode(encoding)
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return string.decode(encodings[0], errors="ignore")
