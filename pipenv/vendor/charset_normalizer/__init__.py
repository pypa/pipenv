"""
Charset-Normalizer
~~~~~~~~~~~~~~
The Real First Universal Charset Detector.
A library that helps you read text from an unknown charset encoding.
Motivated by chardet, This package is trying to resolve the issue by taking a new approach.
All IANA character set names for which the Python core library provides codecs are supported.

Basic usage:
   >>> from charset_normalizer import from_bytes
   >>> results = from_bytes('Bсеки човек има право на образование. Oбразованието трябва да бъде безплатно, поне що се отнася до началното и основното образование.'.encode('utf_8'))
   >>> "utf_8" in results
   True
   >>> best_result = results.best()
   >>> str(best_result)
   'Bсеки човек има право на образование. Oбразованието трябва да бъде безплатно, поне що се отнася до началното и основното образование.'

Others methods and usages are available - see the full documentation
at <https://github.com/Ousret/charset_normalizer>.
:copyright: (c) 2021 by Ahmed TAHRI
:license: MIT, see LICENSE for more details.
"""
from charset_normalizer.api import from_fp, from_path, from_bytes, normalize
from charset_normalizer.legacy import detect
from charset_normalizer.version import __version__, VERSION
from charset_normalizer.models import CharsetMatch, CharsetMatches

# Backward-compatible v1 imports
from charset_normalizer.models import CharsetNormalizerMatch
import charset_normalizer.api as CharsetDetector
CharsetNormalizerMatches = CharsetDetector
