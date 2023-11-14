# coding: utf-8

# Abstract classes.

from typing import Any, Dict, Optional, List  # NOQA
from pipenv.vendor.ruamel.yaml.tag import Tag

SHOW_LINES = False


def CommentCheck() -> None:
    pass


class Event:
    __slots__ = 'start_mark', 'end_mark', 'comment'
    crepr = 'Unspecified Event'

    def __init__(
        self, start_mark: Any = None, end_mark: Any = None, comment: Any = CommentCheck,
    ) -> None:
        self.start_mark = start_mark
        self.end_mark = end_mark
        # assert comment is not CommentCheck
        if comment is CommentCheck:
            comment = None
        self.comment = comment

    def __repr__(self) -> Any:
        if True:
            arguments = []
            if hasattr(self, 'value'):
                # if you use repr(getattr(self, 'value')) then flake8 complains about
                # abuse of getattr with a constant. When you change to self.value
                # then mypy throws an error
                arguments.append(repr(self.value))
            for key in ['anchor', 'tag', 'implicit', 'flow_style', 'style']:
                v = getattr(self, key, None)
                if v is not None:
                    arguments.append(f'{key!s}={v!r}')
            if self.comment not in [None, CommentCheck]:
                arguments.append(f'comment={self.comment!r}')
            if SHOW_LINES:
                arguments.append(
                    f'({self.start_mark.line}:{self.start_mark.column}/'
                    f'{self.end_mark.line}:{self.end_mark.column})',
                )
            arguments = ', '.join(arguments)  # type: ignore
        else:
            attributes = [
                key
                for key in ['anchor', 'tag', 'implicit', 'value', 'flow_style', 'style']
                if hasattr(self, key)
            ]
            arguments = ', '.join([f'{key!s}={getattr(self, key)!r}' for key in attributes])
            if self.comment not in [None, CommentCheck]:
                arguments += f', comment={self.comment!r}'
        return f'{self.__class__.__name__!s}({arguments!s})'

    def compact_repr(self) -> str:
        return f'{self.crepr}'


class NodeEvent(Event):
    __slots__ = ('anchor',)

    def __init__(
        self, anchor: Any, start_mark: Any = None, end_mark: Any = None, comment: Any = None,
    ) -> None:
        Event.__init__(self, start_mark, end_mark, comment)
        self.anchor = anchor


class CollectionStartEvent(NodeEvent):
    __slots__ = 'ctag', 'implicit', 'flow_style', 'nr_items'

    def __init__(
        self,
        anchor: Any,
        tag: Any,
        implicit: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        flow_style: Any = None,
        comment: Any = None,
        nr_items: Optional[int] = None,
    ) -> None:
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.ctag = tag
        self.implicit = implicit
        self.flow_style = flow_style
        self.nr_items = nr_items

    @property
    def tag(self) -> Optional[str]:
        return None if self.ctag is None else str(self.ctag)


class CollectionEndEvent(Event):
    __slots__ = ()


# Implementations.


class StreamStartEvent(Event):
    __slots__ = ('encoding',)
    crepr = '+STR'

    def __init__(
        self,
        start_mark: Any = None,
        end_mark: Any = None,
        encoding: Any = None,
        comment: Any = None,
    ) -> None:
        Event.__init__(self, start_mark, end_mark, comment)
        self.encoding = encoding


class StreamEndEvent(Event):
    __slots__ = ()
    crepr = '-STR'


class DocumentStartEvent(Event):
    __slots__ = 'explicit', 'version', 'tags'
    crepr = '+DOC'

    def __init__(
        self,
        start_mark: Any = None,
        end_mark: Any = None,
        explicit: Any = None,
        version: Any = None,
        tags: Any = None,
        comment: Any = None,
    ) -> None:
        Event.__init__(self, start_mark, end_mark, comment)
        self.explicit = explicit
        self.version = version
        self.tags = tags

    def compact_repr(self) -> str:
        start = ' ---' if self.explicit else ''
        return f'{self.crepr}{start}'


class DocumentEndEvent(Event):
    __slots__ = ('explicit',)
    crepr = '-DOC'

    def __init__(
        self,
        start_mark: Any = None,
        end_mark: Any = None,
        explicit: Any = None,
        comment: Any = None,
    ) -> None:
        Event.__init__(self, start_mark, end_mark, comment)
        self.explicit = explicit

    def compact_repr(self) -> str:
        end = ' ...' if self.explicit else ''
        return f'{self.crepr}{end}'


class AliasEvent(NodeEvent):
    __slots__ = 'style'
    crepr = '=ALI'

    def __init__(
        self,
        anchor: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        style: Any = None,
        comment: Any = None,
    ) -> None:
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.style = style

    def compact_repr(self) -> str:
        return f'{self.crepr} *{self.anchor}'


class ScalarEvent(NodeEvent):
    __slots__ = 'ctag', 'implicit', 'value', 'style'
    crepr = '=VAL'

    def __init__(
        self,
        anchor: Any,
        tag: Any,
        implicit: Any,
        value: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        style: Any = None,
        comment: Any = None,
    ) -> None:
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.ctag = tag
        self.implicit = implicit
        self.value = value
        self.style = style

    @property
    def tag(self) -> Optional[str]:
        return None if self.ctag is None else str(self.ctag)

    @tag.setter
    def tag(self, val: Any) -> None:
        if isinstance(val, str):
            val = Tag(suffix=val)
        self.ctag = val

    def compact_repr(self) -> str:
        style = ':' if self.style is None else self.style
        anchor = f'&{self.anchor} ' if self.anchor else ''
        tag = f'<{self.tag!s}> ' if self.tag else ''
        value = self.value
        for ch, rep in [
            ('\\', '\\\\'),
            ('\t', '\\t'),
            ('\n', '\\n'),
            ('\a', ''),  # remove from folded
            ('\r', '\\r'),
            ('\b', '\\b'),
        ]:
            value = value.replace(ch, rep)
        return f'{self.crepr} {anchor}{tag}{style}{value}'


class SequenceStartEvent(CollectionStartEvent):
    __slots__ = ()
    crepr = '+SEQ'

    def compact_repr(self) -> str:
        flow = ' []' if self.flow_style else ''
        anchor = f' &{self.anchor}' if self.anchor else ''
        tag = f' <{self.tag!s}>' if self.tag else ''
        return f'{self.crepr}{flow}{anchor}{tag}'


class SequenceEndEvent(CollectionEndEvent):
    __slots__ = ()
    crepr = '-SEQ'


class MappingStartEvent(CollectionStartEvent):
    __slots__ = ()
    crepr = '+MAP'

    def compact_repr(self) -> str:
        flow = ' {}' if self.flow_style else ''
        anchor = f' &{self.anchor}' if self.anchor else ''
        tag = f' <{self.tag!s}>' if self.tag else ''
        return f'{self.crepr}{flow}{anchor}{tag}'


class MappingEndEvent(CollectionEndEvent):
    __slots__ = ()
    crepr = '-MAP'
