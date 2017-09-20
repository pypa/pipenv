#!/usr/bin/env python
# encoding: utf-8
"""
process.py

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

from . import fuzz
from . import utils
import heapq
import logging
from functools import partial


default_scorer = fuzz.WRatio


default_processor = utils.full_process


def extractWithoutOrder(query, choices, processor=default_processor, scorer=default_scorer, score_cutoff=0):
    """Select the best match in a list or dictionary of choices.

    Find best matches in a list or dictionary of choices, return a
    generator of tuples containing the match and its score. If a dictionary
    is used, also returns the key for each match.

    Arguments:
        query: An object representing the thing we want to find.
        choices: An iterable or dictionary-like object containing choices
            to be matched against the query. Dictionary arguments of
            {key: value} pairs will attempt to match the query against
            each value.
        processor: Optional function of the form f(a) -> b, where a is the query or
            individual choice and b is the choice to be used in matching.

            This can be used to match against, say, the first element of
            a list:

            lambda x: x[0]

            Defaults to fuzzywuzzy.utils.full_process().
        scorer: Optional function for scoring matches between the query and
            an individual processed choice. This should be a function
            of the form f(query, choice) -> int.

            By default, fuzz.WRatio() is used and expects both query and
            choice to be strings.
        score_cutoff: Optional argument for score threshold. No matches with
            a score less than this number will be returned. Defaults to 0.

    Returns:
        Generator of tuples containing the match and its score.

        If a list is used for choices, then the result will be 2-tuples.
        If a dictionary is used, then the result will be 3-tuples containing
        the key for each match.

        For example, searching for 'bird' in the dictionary

        {'bard': 'train', 'dog': 'man'}

        may return

        ('train', 22, 'bard'), ('man', 0, 'dog')
    """
    # Catch generators without lengths
    def no_process(x):
        return x

    try:
        if choices is None or len(choices) == 0:
            raise StopIteration
    except TypeError:
        pass

    # If the processor was removed by setting it to None
    # perfom a noop as it still needs to be a function
    if processor is None:
        processor = no_process

    # Run the processor on the input query.
    processed_query = processor(query)

    if len(processed_query) == 0:
        logging.warning(u"Applied processor reduces input query to empty string, "
                        "all comparisons will have score 0. "
                        "[Query: \'{0}\']".format(query))

    # Don't run full_process twice
    if scorer in [fuzz.WRatio, fuzz.QRatio,
                  fuzz.token_set_ratio, fuzz.token_sort_ratio,
                  fuzz.partial_token_set_ratio, fuzz.partial_token_sort_ratio,
                  fuzz.UWRatio, fuzz.UQRatio] \
            and processor == utils.full_process:
        processor = no_process

    # Only process the query once instead of for every choice
    if scorer in [fuzz.UWRatio, fuzz.UQRatio]:
        pre_processor = partial(utils.full_process, force_ascii=False)
        scorer = partial(scorer, full_process=False)
    elif scorer in [fuzz.WRatio, fuzz.QRatio,
                    fuzz.token_set_ratio, fuzz.token_sort_ratio,
                    fuzz.partial_token_set_ratio, fuzz.partial_token_sort_ratio]:
        pre_processor = partial(utils.full_process, force_ascii=True)
        scorer = partial(scorer, full_process=False)
    else:
        pre_processor = no_process
    processed_query = pre_processor(processed_query)

    try:
        # See if choices is a dictionary-like object.
        for key, choice in choices.items():
            processed = pre_processor(processor(choice))
            score = scorer(processed_query, processed)
            if score >= score_cutoff:
                yield (choice, score, key)
    except AttributeError:
        # It's a list; just iterate over it.
        for choice in choices:
            processed = pre_processor(processor(choice))
            score = scorer(processed_query, processed)
            if score >= score_cutoff:
                yield (choice, score)


def extract(query, choices, processor=default_processor, scorer=default_scorer, limit=5):
    """Select the best match in a list or dictionary of choices.

    Find best matches in a list or dictionary of choices, return a
    list of tuples containing the match and its score. If a dictionary
    is used, also returns the key for each match.

    Arguments:
        query: An object representing the thing we want to find.
        choices: An iterable or dictionary-like object containing choices
            to be matched against the query. Dictionary arguments of
            {key: value} pairs will attempt to match the query against
            each value.
        processor: Optional function of the form f(a) -> b, where a is the query or
            individual choice and b is the choice to be used in matching.

            This can be used to match against, say, the first element of
            a list:

            lambda x: x[0]

            Defaults to fuzzywuzzy.utils.full_process().
        scorer: Optional function for scoring matches between the query and
            an individual processed choice. This should be a function
            of the form f(query, choice) -> int.
            By default, fuzz.WRatio() is used and expects both query and
            choice to be strings.
        limit: Optional maximum for the number of elements returned. Defaults
            to 5.

    Returns:
        List of tuples containing the match and its score.

        If a list is used for choices, then the result will be 2-tuples.
        If a dictionary is used, then the result will be 3-tuples containing
        the key for each match.

        For example, searching for 'bird' in the dictionary

        {'bard': 'train', 'dog': 'man'}

        may return

        [('train', 22, 'bard'), ('man', 0, 'dog')]
    """
    sl = extractWithoutOrder(query, choices, processor, scorer)
    return heapq.nlargest(limit, sl, key=lambda i: i[1]) if limit is not None else \
        sorted(sl, key=lambda i: i[1], reverse=True)


def extractBests(query, choices, processor=default_processor, scorer=default_scorer, score_cutoff=0, limit=5):
    """Get a list of the best matches to a collection of choices.

    Convenience function for getting the choices with best scores.

    Args:
        query: A string to match against
        choices: A list or dictionary of choices, suitable for use with
            extract().
        processor: Optional function for transforming choices before matching.
            See extract().
        scorer: Scoring function for extract().
        score_cutoff: Optional argument for score threshold. No matches with
            a score less than this number will be returned. Defaults to 0.
        limit: Optional maximum for the number of elements returned. Defaults
            to 5.

    Returns: A a list of (match, score) tuples.
    """

    best_list = extractWithoutOrder(query, choices, processor, scorer, score_cutoff)
    return heapq.nlargest(limit, best_list, key=lambda i: i[1]) if limit is not None else \
        sorted(best_list, key=lambda i: i[1], reverse=True)


def extractOne(query, choices, processor=default_processor, scorer=default_scorer, score_cutoff=0):
    """Find the single best match above a score in a list of choices.

    This is a convenience method which returns the single best choice.
    See extract() for the full arguments list.

    Args:
        query: A string to match against
        choices: A list or dictionary of choices, suitable for use with
            extract().
        processor: Optional function for transforming choices before matching.
            See extract().
        scorer: Scoring function for extract().
        score_cutoff: Optional argument for score threshold. If the best
            match is found, but it is not greater than this number, then
            return None anyway ("not a good enough match").  Defaults to 0.

    Returns:
        A tuple containing a single match and its score, if a match
        was found that was above score_cutoff. Otherwise, returns None.
    """
    best_list = extractWithoutOrder(query, choices, processor, scorer, score_cutoff)
    try:
        return max(best_list, key=lambda i: i[1])
    except ValueError:
        return None


def dedupe(contains_dupes, threshold=70, scorer=fuzz.token_set_ratio):
    """This convenience function takes a list of strings containing duplicates and uses fuzzy matching to identify
    and remove duplicates. Specifically, it uses the process.extract to identify duplicates that
    score greater than a user defined threshold. Then, it looks for the longest item in the duplicate list
    since we assume this item contains the most entity information and returns that. It breaks string
    length ties on an alphabetical sort.

    Note: as the threshold DECREASES the number of duplicates that are found INCREASES. This means that the
        returned deduplicated list will likely be shorter. Raise the threshold for fuzzy_dedupe to be less
        sensitive.

    Args:
        contains_dupes: A list of strings that we would like to dedupe.
        threshold: the numerical value (0,100) point at which we expect to find duplicates.
            Defaults to 70 out of 100
        scorer: Optional function for scoring matches between the query and
            an individual processed choice. This should be a function
            of the form f(query, choice) -> int.
            By default, fuzz.token_set_ratio() is used and expects both query and
            choice to be strings.

    Returns:
        A deduplicated list. For example:

            In: contains_dupes = ['Frodo Baggin', 'Frodo Baggins', 'F. Baggins', 'Samwise G.', 'Gandalf', 'Bilbo Baggins']
            In: fuzzy_dedupe(contains_dupes)
            Out: ['Frodo Baggins', 'Samwise G.', 'Bilbo Baggins', 'Gandalf']
        """

    extractor = []

    # iterate over items in *contains_dupes*
    for item in contains_dupes:
        # return all duplicate matches found
        matches = extract(item, contains_dupes, limit=None, scorer=scorer)
        # filter matches based on the threshold
        filtered = [x for x in matches if x[1] > threshold]
        # if there is only 1 item in *filtered*, no duplicates were found so append to *extracted*
        if len(filtered) == 1:
            extractor.append(filtered[0][0])

        else:
            # alpha sort
            filtered = sorted(filtered, key=lambda x: x[0])
            # length sort
            filter_sort = sorted(filtered, key=lambda x: len(x[0]), reverse=True)
            # take first item as our 'canonical example'
            extractor.append(filter_sort[0][0])

    # uniquify *extractor* list
    keys = {}
    for e in extractor:
        keys[e] = 1
    extractor = keys.keys()

    # check that extractor differs from contain_dupes (e.g. duplicates were found)
    # if not, then return the original list
    if len(extractor) == len(contains_dupes):
        return contains_dupes
    else:
        return extractor
