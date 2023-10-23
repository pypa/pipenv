# coding: utf-8

import sys

from typing import Dict, Any, Text, Optional  # NOQA
from pipenv.vendor.ruamel.yaml.tag import Tag


class Node:
    __slots__ = 'ctag', 'value', 'start_mark', 'end_mark', 'comment', 'anchor'

    def __init__(
        self,
        tag: Any,
        value: Any,
        start_mark: Any,
        end_mark: Any,
        comment: Any = None,
        anchor: Any = None,
    ) -> None:
        # you can still get a string from the serializer
        self.ctag = tag if isinstance(tag, Tag) else Tag(suffix=tag)
        self.value = value
        self.start_mark = start_mark
        self.end_mark = end_mark
        self.comment = comment
        self.anchor = anchor

    @property
    def tag(self) -> Optional[str]:
        return None if self.ctag is None else str(self.ctag)

    @tag.setter
    def tag(self, val: Any) -> None:
        if isinstance(val, str):
            val = Tag(suffix=val)
        self.ctag = val

    def __repr__(self) -> Any:
        value = self.value
        # if isinstance(value, list):
        #     if len(value) == 0:
        #         value = '<empty>'
        #     elif len(value) == 1:
        #         value = '<1 item>'
        #     else:
        #         value = f'<{len(value)} items>'
        # else:
        #     if len(value) > 75:
        #         value = repr(value[:70]+' ... ')
        #     else:
        #         value = repr(value)
        value = repr(value)
        return f'{self.__class__.__name__!s}(tag={self.tag!r}, value={value!s})'

    def dump(self, indent: int = 0) -> None:
        xx = self.__class__.__name__
        xi = '  ' * indent
        if isinstance(self.value, str):
            sys.stdout.write(f'{xi}{xx}(tag={self.tag!r}, value={self.value!r})\n')
            if self.comment:
                sys.stdout.write(f'    {xi}comment: {self.comment})\n')
            return
        sys.stdout.write(f'{xi}{xx}(tag={self.tag!r})\n')
        if self.comment:
            sys.stdout.write(f'    {xi}comment: {self.comment})\n')
        for v in self.value:
            if isinstance(v, tuple):
                for v1 in v:
                    v1.dump(indent + 1)
            elif isinstance(v, Node):
                v.dump(indent + 1)
            else:
                sys.stdout.write(f'Node value type? {type(v)}\n')


class ScalarNode(Node):
    """
    styles:
      ? -> set() ? key, no value
      " -> double quoted
      ' -> single quoted
      | -> literal style
      > -> folding style
    """

    __slots__ = ('style',)
    id = 'scalar'

    def __init__(
        self,
        tag: Any,
        value: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        style: Any = None,
        comment: Any = None,
        anchor: Any = None,
    ) -> None:
        Node.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        self.style = style


class CollectionNode(Node):
    __slots__ = ('flow_style',)

    def __init__(
        self,
        tag: Any,
        value: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        flow_style: Any = None,
        comment: Any = None,
        anchor: Any = None,
    ) -> None:
        Node.__init__(self, tag, value, start_mark, end_mark, comment=comment)
        self.flow_style = flow_style
        self.anchor = anchor


class SequenceNode(CollectionNode):
    __slots__ = ()
    id = 'sequence'


class MappingNode(CollectionNode):
    __slots__ = ('merge',)
    id = 'mapping'

    def __init__(
        self,
        tag: Any,
        value: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        flow_style: Any = None,
        comment: Any = None,
        anchor: Any = None,
    ) -> None:
        CollectionNode.__init__(
            self, tag, value, start_mark, end_mark, flow_style, comment, anchor,
        )
        self.merge = None
