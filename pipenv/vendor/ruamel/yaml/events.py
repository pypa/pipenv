# coding: utf-8

from pipenv.vendor.ruamel.yaml.compat import _F

# Abstract classes.

if False:  # MYPY
    from typing import Any, Dict, Optional, List  # NOQA

SHOW_LINES = False


def CommentCheck():
    # type: () -> None
    pass


class Event:
    __slots__ = 'start_mark', 'end_mark', 'comment'

    def __init__(self, start_mark=None, end_mark=None, comment=CommentCheck):
        # type: (Any, Any, Any) -> None
        self.start_mark = start_mark
        self.end_mark = end_mark
        # assert comment is not CommentCheck
        if comment is CommentCheck:
            comment = None
        self.comment = comment

    def __repr__(self):
        # type: () -> Any
        if True:
            arguments = []
            if hasattr(self, 'value'):
                # if you use repr(getattr(self, 'value')) then flake8 complains about
                # abuse of getattr with a constant. When you change to self.value
                # then mypy throws an error
                arguments.append(repr(self.value))  # type: ignore
            for key in ['anchor', 'tag', 'implicit', 'flow_style', 'style']:
                v = getattr(self, key, None)
                if v is not None:
                    arguments.append(_F('{key!s}={v!r}', key=key, v=v))
            if self.comment not in [None, CommentCheck]:
                arguments.append('comment={!r}'.format(self.comment))
            if SHOW_LINES:
                arguments.append(
                    '({}:{}/{}:{})'.format(
                        self.start_mark.line,
                        self.start_mark.column,
                        self.end_mark.line,
                        self.end_mark.column,
                    )
                )
            arguments = ', '.join(arguments)  # type: ignore
        else:
            attributes = [
                key
                for key in ['anchor', 'tag', 'implicit', 'value', 'flow_style', 'style']
                if hasattr(self, key)
            ]
            arguments = ', '.join(
                [_F('{k!s}={attr!r}', k=key, attr=getattr(self, key)) for key in attributes]
            )
            if self.comment not in [None, CommentCheck]:
                arguments += ', comment={!r}'.format(self.comment)
        return _F(
            '{self_class_name!s}({arguments!s})',
            self_class_name=self.__class__.__name__,
            arguments=arguments,
        )


class NodeEvent(Event):
    __slots__ = ('anchor',)

    def __init__(self, anchor, start_mark=None, end_mark=None, comment=None):
        # type: (Any, Any, Any, Any) -> None
        Event.__init__(self, start_mark, end_mark, comment)
        self.anchor = anchor


class CollectionStartEvent(NodeEvent):
    __slots__ = 'tag', 'implicit', 'flow_style', 'nr_items'

    def __init__(
        self,
        anchor,
        tag,
        implicit,
        start_mark=None,
        end_mark=None,
        flow_style=None,
        comment=None,
        nr_items=None,
    ):
        # type: (Any, Any, Any, Any, Any, Any, Any, Optional[int]) -> None
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.tag = tag
        self.implicit = implicit
        self.flow_style = flow_style
        self.nr_items = nr_items


class CollectionEndEvent(Event):
    __slots__ = ()


# Implementations.


class StreamStartEvent(Event):
    __slots__ = ('encoding',)

    def __init__(self, start_mark=None, end_mark=None, encoding=None, comment=None):
        # type: (Any, Any, Any, Any) -> None
        Event.__init__(self, start_mark, end_mark, comment)
        self.encoding = encoding


class StreamEndEvent(Event):
    __slots__ = ()


class DocumentStartEvent(Event):
    __slots__ = 'explicit', 'version', 'tags'

    def __init__(
        self,
        start_mark=None,
        end_mark=None,
        explicit=None,
        version=None,
        tags=None,
        comment=None,
    ):
        # type: (Any, Any, Any, Any, Any, Any) -> None
        Event.__init__(self, start_mark, end_mark, comment)
        self.explicit = explicit
        self.version = version
        self.tags = tags


class DocumentEndEvent(Event):
    __slots__ = ('explicit',)

    def __init__(self, start_mark=None, end_mark=None, explicit=None, comment=None):
        # type: (Any, Any, Any, Any) -> None
        Event.__init__(self, start_mark, end_mark, comment)
        self.explicit = explicit


class AliasEvent(NodeEvent):
    __slots__ = 'style'

    def __init__(self, anchor, start_mark=None, end_mark=None, style=None, comment=None):
        # type: (Any, Any, Any, Any, Any) -> None
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.style = style


class ScalarEvent(NodeEvent):
    __slots__ = 'tag', 'implicit', 'value', 'style'

    def __init__(
        self,
        anchor,
        tag,
        implicit,
        value,
        start_mark=None,
        end_mark=None,
        style=None,
        comment=None,
    ):
        # type: (Any, Any, Any, Any, Any, Any, Any, Any) -> None
        NodeEvent.__init__(self, anchor, start_mark, end_mark, comment)
        self.tag = tag
        self.implicit = implicit
        self.value = value
        self.style = style


class SequenceStartEvent(CollectionStartEvent):
    __slots__ = ()


class SequenceEndEvent(CollectionEndEvent):
    __slots__ = ()


class MappingStartEvent(CollectionStartEvent):
    __slots__ = ()


class MappingEndEvent(CollectionEndEvent):
    __slots__ = ()
