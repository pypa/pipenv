from __future__ import division, print_function

import os
from math import ceil
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
try:
    from shutil import get_terminal_size
except ImportError:
    from backports.shutil_get_terminal_size import get_terminal_size

SEP = '  '
L = len(SEP)


def get_rows(venvs, columns_number):
    lines_number = int(ceil(len(venvs) / columns_number))
    for i in range(lines_number):
        yield venvs[i::lines_number]


def row_len(names):
    return sum(map(len, names)) + L * len(names) - L


def get_best_columns_number(venvs):
    max_width, _ = get_terminal_size()
    columns_number = 1
    for columns_number in range(1, len(venvs) + 1):
        rows = get_rows(venvs, columns_number)
        if max(map(row_len, rows)) > max_width:
            return (columns_number - 1) or 1
    else:
        return columns_number


def align_column(column):
    m = max(map(len, column))
    return [name.ljust(m) for name in column]


def columnize(venvs):
    columns_n = get_best_columns_number(venvs)
    columns = map(align_column, zip_longest(*get_rows(venvs, columns_n), fillvalue=''))
    return map(SEP.join, zip(*columns))


def print_virtualenvs(*venvs):
    venvs = sorted(venvs)
    if os.isatty(1):
        print(*columnize(venvs), sep='\n')
    else:
        print(*venvs, sep=' ')
