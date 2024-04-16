
from __future__ import annotations

from pipenv.vendor.ruamel.yaml.anchor import Anchor

if False:  # MYPY
    from typing import Text, Any, Dict, List  # NOQA
    from pipenv.vendor.ruamel.yaml.compat import SupportsIndex

__all__ = [
    'ScalarString',
    'LiteralScalarString',
    'FoldedScalarString',
    'SingleQuotedScalarString',
    'DoubleQuotedScalarString',
    'PlainScalarString',
    # PreservedScalarString is the old name, as it was the first to be preserved on rt,
    # use LiteralScalarString instead
    'PreservedScalarString',
]


class ScalarString(str):
    __slots__ = Anchor.attrib

    def __new__(cls, *args: Any, **kw: Any) -> Any:
        anchor = kw.pop('anchor', None)
        ret_val = str.__new__(cls, *args, **kw)
        if anchor is not None:
            ret_val.yaml_set_anchor(anchor, always_dump=True)
        return ret_val

    def replace(self, old: Any, new: Any, maxreplace: SupportsIndex = -1) -> Any:
        return type(self)((str.replace(self, old, new, maxreplace)))

    @property
    def anchor(self) -> Any:
        if not hasattr(self, Anchor.attrib):
            setattr(self, Anchor.attrib, Anchor())
        return getattr(self, Anchor.attrib)

    def yaml_anchor(self, any: bool = False) -> Any:
        if not hasattr(self, Anchor.attrib):
            return None
        if any or self.anchor.always_dump:
            return self.anchor
        return None

    def yaml_set_anchor(self, value: Any, always_dump: bool = False) -> None:
        self.anchor.value = value
        self.anchor.always_dump = always_dump


class LiteralScalarString(ScalarString):
    __slots__ = 'comment'  # the comment after the | on the first line

    style = '|'

    def __new__(cls, value: Text, anchor: Any = None) -> Any:
        return ScalarString.__new__(cls, value, anchor=anchor)


PreservedScalarString = LiteralScalarString


class FoldedScalarString(ScalarString):
    __slots__ = ('fold_pos', 'comment')  # the comment after the > on the first line

    style = '>'

    def __new__(cls, value: Text, anchor: Any = None) -> Any:
        return ScalarString.__new__(cls, value, anchor=anchor)


class SingleQuotedScalarString(ScalarString):
    __slots__ = ()

    style = "'"

    def __new__(cls, value: Text, anchor: Any = None) -> Any:
        return ScalarString.__new__(cls, value, anchor=anchor)


class DoubleQuotedScalarString(ScalarString):
    __slots__ = ()

    style = '"'

    def __new__(cls, value: Text, anchor: Any = None) -> Any:
        return ScalarString.__new__(cls, value, anchor=anchor)


class PlainScalarString(ScalarString):
    __slots__ = ()

    style = ''

    def __new__(cls, value: Text, anchor: Any = None) -> Any:
        return ScalarString.__new__(cls, value, anchor=anchor)


def preserve_literal(s: Text) -> Text:
    return LiteralScalarString(s.replace('\r\n', '\n').replace('\r', '\n'))


def walk_tree(base: Any, map: Any = None) -> None:
    """
    the routine here walks over a simple yaml tree (recursing in
    dict values and list items) and converts strings that
    have multiple lines to literal scalars

    You can also provide an explicit (ordered) mapping for multiple transforms
    (first of which is executed):
        map = ruamel.compat.ordereddict
        map['\n'] = preserve_literal
        map[':'] = SingleQuotedScalarString
        walk_tree(data, map=map)
    """
    from collections.abc import MutableMapping, MutableSequence

    if map is None:
        map = {'\n': preserve_literal}

    if isinstance(base, MutableMapping):
        for k in base:
            v: Text = base[k]
            if isinstance(v, str):
                for ch in map:
                    if ch in v:
                        base[k] = map[ch](v)
                        break
            else:
                walk_tree(v, map=map)
    elif isinstance(base, MutableSequence):
        for idx, elem in enumerate(base):
            if isinstance(elem, str):
                for ch in map:
                    if ch in elem:
                        base[idx] = map[ch](elem)
                        break
            else:
                walk_tree(elem, map=map)
