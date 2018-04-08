#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import sys

__all__ = ['quote']

if sys.version_info >= (3, 1):
    _find_unsafe = re.compile(r'[^\w@%+=:,./-]', re.ASCII).search
else:
    _find_unsafe = re.compile(r'[^\w@%+=:,./-]').search


def quote(s):
    """Return a shell-escaped version of the string *s*."""
    if not s:
        return "''"
    if _find_unsafe(s) is None:
        return s

    # use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'
    return "'" + s.replace("'", "'\"'\"'") + "'"
