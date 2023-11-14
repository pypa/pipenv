# coding: utf-8

"""
some helper functions that might be generally useful
"""

import datetime
from functools import partial
import re


from typing import Any, Dict, Optional, List, Text, Callable, Union  # NOQA
from .compat import StreamTextType  # NOQA


class LazyEval:
    """
    Lightweight wrapper around lazily evaluated func(*args, **kwargs).

    func is only evaluated when any attribute of its return value is accessed.
    Every attribute access is passed through to the wrapped value.
    (This only excludes special cases like method-wrappers, e.g., __hash__.)
    The sole additional attribute is the lazy_self function which holds the
    return value (or, prior to evaluation, func and arguments), in its closure.
    """

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        def lazy_self() -> Any:
            return_value = func(*args, **kwargs)
            object.__setattr__(self, 'lazy_self', lambda: return_value)
            return return_value

        object.__setattr__(self, 'lazy_self', lazy_self)

    def __getattribute__(self, name: str) -> Any:
        lazy_self = object.__getattribute__(self, 'lazy_self')
        if name == 'lazy_self':
            return lazy_self
        return getattr(lazy_self(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.lazy_self(), name, value)


RegExp = partial(LazyEval, re.compile)

timestamp_regexp = RegExp(
    """^(?P<year>[0-9][0-9][0-9][0-9])
       -(?P<month>[0-9][0-9]?)
       -(?P<day>[0-9][0-9]?)
       (?:((?P<t>[Tt])|[ \\t]+)   # explictly not retaining extra spaces
       (?P<hour>[0-9][0-9]?)
       :(?P<minute>[0-9][0-9])
       :(?P<second>[0-9][0-9])
       (?:\\.(?P<fraction>[0-9]*))?
        (?:[ \\t]*(?P<tz>Z|(?P<tz_sign>[-+])(?P<tz_hour>[0-9][0-9]?)
       (?::(?P<tz_minute>[0-9][0-9]))?))?)?$""",
    re.X,
)


def create_timestamp(
    year: Any,
    month: Any,
    day: Any,
    t: Any,
    hour: Any,
    minute: Any,
    second: Any,
    fraction: Any,
    tz: Any,
    tz_sign: Any,
    tz_hour: Any,
    tz_minute: Any,
) -> Union[datetime.datetime, datetime.date]:
    # create a timestamp from match against timestamp_regexp
    MAX_FRAC = 999999
    year = int(year)
    month = int(month)
    day = int(day)
    if not hour:
        return datetime.date(year, month, day)
    hour = int(hour)
    minute = int(minute)
    second = int(second)
    frac = 0
    if fraction:
        frac_s = fraction[:6]
        while len(frac_s) < 6:
            frac_s += '0'
        frac = int(frac_s)
        if len(fraction) > 6 and int(fraction[6]) > 4:
            frac += 1
        if frac > MAX_FRAC:
            fraction = 0
        else:
            fraction = frac
    else:
        fraction = 0
    delta = None
    if tz_sign:
        tz_hour = int(tz_hour)
        tz_minute = int(tz_minute) if tz_minute else 0
        delta = datetime.timedelta(
            hours=tz_hour, minutes=tz_minute, seconds=1 if frac > MAX_FRAC else 0,
        )
        if tz_sign == '-':
            delta = -delta
    elif frac > MAX_FRAC:
        delta = -datetime.timedelta(seconds=1)
    # should do something else instead (or hook this up to the preceding if statement
    # in reverse
    #  if delta is None:
    #      return datetime.datetime(year, month, day, hour, minute, second, fraction)
    #  return datetime.datetime(year, month, day, hour, minute, second, fraction,
    #                           datetime.timezone.utc)
    # the above is not good enough though, should provide tzinfo. In Python3 that is easily
    # doable drop that kind of support for Python2 as it has not native tzinfo
    data = datetime.datetime(year, month, day, hour, minute, second, fraction)
    if delta:
        data -= delta
    return data


# originally as comment
# https://github.com/pre-commit/pre-commit/pull/211#issuecomment-186466605
# if you use this in your code, I suggest adding a test in your test suite
# that check this routines output against a known piece of your YAML
# before upgrades to this code break your round-tripped YAML
def load_yaml_guess_indent(stream: StreamTextType, **kw: Any) -> Any:
    """guess the indent and block sequence indent of yaml stream/string

    returns round_trip_loaded stream, indent level, block sequence indent
    - block sequence indent is the number of spaces before a dash relative to previous indent
    - if there are no block sequences, indent is taken from nested mappings, block sequence
      indent is unset (None) in that case
    """
    from .main import YAML

    # load a YAML document, guess the indentation, if you use TABs you are on your own
    def leading_spaces(line: Any) -> int:
        idx = 0
        while idx < len(line) and line[idx] == ' ':
            idx += 1
        return idx

    if isinstance(stream, str):
        yaml_str: Any = stream
    elif isinstance(stream, bytes):
        # most likely, but the Reader checks BOM for this
        yaml_str = stream.decode('utf-8')
    else:
        yaml_str = stream.read()
    map_indent = None
    indent = None  # default if not found for some reason
    block_seq_indent = None
    prev_line_key_only = None
    key_indent = 0
    for line in yaml_str.splitlines():
        rline = line.rstrip()
        lline = rline.lstrip()
        if lline.startswith('- '):
            l_s = leading_spaces(line)
            block_seq_indent = l_s - key_indent
            idx = l_s + 1
            while line[idx] == ' ':  # this will end as we rstripped
                idx += 1
            if line[idx] == '#':  # comment after -
                continue
            indent = idx - key_indent
            break
        if map_indent is None and prev_line_key_only is not None and rline:
            idx = 0
            while line[idx] in ' -':
                idx += 1
            if idx > prev_line_key_only:
                map_indent = idx - prev_line_key_only
        if rline.endswith(':'):
            key_indent = leading_spaces(line)
            idx = 0
            while line[idx] == ' ':  # this will end on ':'
                idx += 1
            prev_line_key_only = idx
            continue
        prev_line_key_only = None
    if indent is None and map_indent is not None:
        indent = map_indent
    yaml = YAML()
    return yaml.load(yaml_str, **kw), indent, block_seq_indent


def configobj_walker(cfg: Any) -> Any:
    """
    walks over a ConfigObj (INI file with comments) generating
    corresponding YAML output (including comments
    """
    from configobj import ConfigObj  # type: ignore

    assert isinstance(cfg, ConfigObj)
    for c in cfg.initial_comment:
        if c.strip():
            yield c
    for s in _walk_section(cfg):
        if s.strip():
            yield s
    for c in cfg.final_comment:
        if c.strip():
            yield c


def _walk_section(s: Any, level: int = 0) -> Any:
    from configobj import Section

    assert isinstance(s, Section)
    indent = '  ' * level
    for name in s.scalars:
        for c in s.comments[name]:
            yield indent + c.strip()
        x = s[name]
        if '\n' in x:
            i = indent + '  '
            x = '|\n' + i + x.strip().replace('\n', '\n' + i)
        elif ':' in x:
            x = "'" + x.replace("'", "''") + "'"
        line = f'{indent}{name}: {x}'
        c = s.inline_comments[name]
        if c:
            line += ' ' + c
        yield line
    for name in s.sections:
        for c in s.comments[name]:
            yield indent + c.strip()
        line = f'{indent}{name}:'
        c = s.inline_comments[name]
        if c:
            line += ' ' + c
        yield line
        for val in _walk_section(s[name], level=level + 1):
            yield val


# def config_obj_2_rt_yaml(cfg):
#     from .comments import CommentedMap, CommentedSeq
#     from configobj import ConfigObj
#     assert isinstance(cfg, ConfigObj)
#     #for c in cfg.initial_comment:
#     #    if c.strip():
#     #        pass
#     cm = CommentedMap()
#     for name in s.sections:
#         cm[name] = d = CommentedMap()
#
#
#     #for c in cfg.final_comment:
#     #    if c.strip():
#     #        yield c
#     return cm
