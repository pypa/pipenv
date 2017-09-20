#!/usr/bin/env python
# encoding: utf-8
"""
fuzz.py

Copyright (c) 2011 Adam Cohen

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
from __future__ import unicode_literals
import platform
import warnings

try:
    from .StringMatcher import StringMatcher as SequenceMatcher
except ImportError:
    if platform.python_implementation() != "PyPy":
        # warnings.warn('Using slow pure-python SequenceMatcher. Install python-Levenshtein to remove this warning')
        pass
    from difflib import SequenceMatcher

from . import utils


###########################
# Basic Scoring Functions #
###########################

@utils.check_for_none
@utils.check_empty_string
def ratio(s1, s2):
    s1, s2 = utils.make_type_consistent(s1, s2)

    m = SequenceMatcher(None, s1, s2)
    return utils.intr(100 * m.ratio())


@utils.check_for_none
@utils.check_empty_string
def partial_ratio(s1, s2):
    """"Return the ratio of the most similar substring
    as a number between 0 and 100."""
    s1, s2 = utils.make_type_consistent(s1, s2)

    if len(s1) <= len(s2):
        shorter = s1
        longer = s2
    else:
        shorter = s2
        longer = s1

    m = SequenceMatcher(None, shorter, longer)
    blocks = m.get_matching_blocks()

    # each block represents a sequence of matching characters in a string
    # of the form (idx_1, idx_2, len)
    # the best partial match will block align with at least one of those blocks
    #   e.g. shorter = "abcd", longer = XXXbcdeEEE
    #   block = (1,3,3)
    #   best score === ratio("abcd", "Xbcd")
    scores = []
    for block in blocks:
        long_start = block[1] - block[0] if (block[1] - block[0]) > 0 else 0
        long_end = long_start + len(shorter)
        long_substr = longer[long_start:long_end]

        m2 = SequenceMatcher(None, shorter, long_substr)
        r = m2.ratio()
        if r > .995:
            return 100
        else:
            scores.append(r)

    return utils.intr(100 * max(scores))


##############################
# Advanced Scoring Functions #
##############################

def _process_and_sort(s, force_ascii, full_process=True):
    """Return a cleaned string with token sorted."""
    # pull tokens
    ts = utils.full_process(s, force_ascii=force_ascii) if full_process else s
    tokens = ts.split()

    # sort tokens and join
    sorted_string = u" ".join(sorted(tokens))
    return sorted_string.strip()


# Sorted Token
#   find all alphanumeric tokens in the string
#   sort those tokens and take ratio of resulting joined strings
#   controls for unordered string elements
@utils.check_for_none
def _token_sort(s1, s2, partial=True, force_ascii=True, full_process=True):
    sorted1 = _process_and_sort(s1, force_ascii, full_process=full_process)
    sorted2 = _process_and_sort(s2, force_ascii, full_process=full_process)

    if partial:
        return partial_ratio(sorted1, sorted2)
    else:
        return ratio(sorted1, sorted2)


def token_sort_ratio(s1, s2, force_ascii=True, full_process=True):
    """Return a measure of the sequences' similarity between 0 and 100
    but sorting the token before comparing.
    """
    return _token_sort(s1, s2, partial=False, force_ascii=force_ascii, full_process=full_process)


def partial_token_sort_ratio(s1, s2, force_ascii=True, full_process=True):
    """Return the ratio of the most similar substring as a number between
    0 and 100 but sorting the token before comparing.
    """
    return _token_sort(s1, s2, partial=True, force_ascii=force_ascii, full_process=full_process)


@utils.check_for_none
def _token_set(s1, s2, partial=True, force_ascii=True, full_process=True):
    """Find all alphanumeric tokens in each string...
        - treat them as a set
        - construct two strings of the form:
            <sorted_intersection><sorted_remainder>
        - take ratios of those two strings
        - controls for unordered partial matches"""

    p1 = utils.full_process(s1, force_ascii=force_ascii) if full_process else s1
    p2 = utils.full_process(s2, force_ascii=force_ascii) if full_process else s2

    if not utils.validate_string(p1):
        return 0
    if not utils.validate_string(p2):
        return 0

    # pull tokens
    tokens1 = set(p1.split())
    tokens2 = set(p2.split())

    intersection = tokens1.intersection(tokens2)
    diff1to2 = tokens1.difference(tokens2)
    diff2to1 = tokens2.difference(tokens1)

    sorted_sect = " ".join(sorted(intersection))
    sorted_1to2 = " ".join(sorted(diff1to2))
    sorted_2to1 = " ".join(sorted(diff2to1))

    combined_1to2 = sorted_sect + " " + sorted_1to2
    combined_2to1 = sorted_sect + " " + sorted_2to1

    # strip
    sorted_sect = sorted_sect.strip()
    combined_1to2 = combined_1to2.strip()
    combined_2to1 = combined_2to1.strip()

    if partial:
        ratio_func = partial_ratio
    else:
        ratio_func = ratio

    pairwise = [
        ratio_func(sorted_sect, combined_1to2),
        ratio_func(sorted_sect, combined_2to1),
        ratio_func(combined_1to2, combined_2to1)
    ]
    return max(pairwise)


def token_set_ratio(s1, s2, force_ascii=True, full_process=True):
    return _token_set(s1, s2, partial=False, force_ascii=force_ascii, full_process=full_process)


def partial_token_set_ratio(s1, s2, force_ascii=True, full_process=True):
    return _token_set(s1, s2, partial=True, force_ascii=force_ascii, full_process=full_process)


###################
# Combination API #
###################

# q is for quick
def QRatio(s1, s2, force_ascii=True, full_process=True):
    """
    Quick ratio comparison between two strings.

    Runs full_process from utils on both strings
    Short circuits if either of the strings is empty after processing.

    :param s1:
    :param s2:
    :param force_ascii: Allow only ASCII characters (Default: True)
    :full_process: Process inputs, used here to avoid double processing in extract functions (Default: True)
    :return: similarity ratio
    """

    if full_process:
        p1 = utils.full_process(s1, force_ascii=force_ascii)
        p2 = utils.full_process(s2, force_ascii=force_ascii)
    else:
        p1 = s1
        p2 = s2

    if not utils.validate_string(p1):
        return 0
    if not utils.validate_string(p2):
        return 0

    return ratio(p1, p2)


def UQRatio(s1, s2, full_process=True):
    """
    Unicode quick ratio

    Calls QRatio with force_ascii set to False

    :param s1:
    :param s2:
    :return: similarity ratio
    """
    return QRatio(s1, s2, force_ascii=False, full_process=full_process)


# w is for weighted
def WRatio(s1, s2, force_ascii=True, full_process=True):
    """
    Return a measure of the sequences' similarity between 0 and 100, using different algorithms.

    **Steps in the order they occur**

    #. Run full_process from utils on both strings
    #. Short circuit if this makes either string empty
    #. Take the ratio of the two processed strings (fuzz.ratio)
    #. Run checks to compare the length of the strings
        * If one of the strings is more than 1.5 times as long as the other
          use partial_ratio comparisons - scale partial results by 0.9
          (this makes sure only full results can return 100)
        * If one of the strings is over 8 times as long as the other
          instead scale by 0.6

    #. Run the other ratio functions
        * if using partial ratio functions call partial_ratio,
          partial_token_sort_ratio and partial_token_set_ratio
          scale all of these by the ratio based on length
        * otherwise call token_sort_ratio and token_set_ratio
        * all token based comparisons are scaled by 0.95
          (on top of any partial scalars)

    #. Take the highest value from these results
       round it and return it as an integer.

    :param s1:
    :param s2:
    :param force_ascii: Allow only ascii characters
    :type force_ascii: bool
    :full_process: Process inputs, used here to avoid double processing in extract functions (Default: True)
    :return:
    """

    if full_process:
        p1 = utils.full_process(s1, force_ascii=force_ascii)
        p2 = utils.full_process(s2, force_ascii=force_ascii)
    else:
        p1 = s1
        p2 = s2

    if not utils.validate_string(p1):
        return 0
    if not utils.validate_string(p2):
        return 0

    # should we look at partials?
    try_partial = True
    unbase_scale = .95
    partial_scale = .90

    base = ratio(p1, p2)
    len_ratio = float(max(len(p1), len(p2))) / min(len(p1), len(p2))

    # if strings are similar length, don't use partials
    if len_ratio < 1.5:
        try_partial = False

    # if one string is much much shorter than the other
    if len_ratio > 8:
        partial_scale = .6

    if try_partial:
        partial = partial_ratio(p1, p2) * partial_scale
        ptsor = partial_token_sort_ratio(p1, p2, full_process=False) \
            * unbase_scale * partial_scale
        ptser = partial_token_set_ratio(p1, p2, full_process=False) \
            * unbase_scale * partial_scale

        return utils.intr(max(base, partial, ptsor, ptser))
    else:
        tsor = token_sort_ratio(p1, p2, full_process=False) * unbase_scale
        tser = token_set_ratio(p1, p2, full_process=False) * unbase_scale

        return utils.intr(max(base, tsor, tser))


def UWRatio(s1, s2, full_process=True):
    """Return a measure of the sequences' similarity between 0 and 100,
    using different algorithms. Same as WRatio but preserving unicode.
    """
    return WRatio(s1, s2, force_ascii=False, full_process=full_process)
