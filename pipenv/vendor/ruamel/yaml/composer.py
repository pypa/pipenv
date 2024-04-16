
from __future__ import annotations

import warnings

from pipenv.vendor.ruamel.yaml.error import MarkedYAMLError, ReusedAnchorWarning
from pipenv.vendor.ruamel.yaml.compat import nprint, nprintf  # NOQA

from pipenv.vendor.ruamel.yaml.events import (
    StreamStartEvent,
    StreamEndEvent,
    MappingStartEvent,
    MappingEndEvent,
    SequenceStartEvent,
    SequenceEndEvent,
    AliasEvent,
    ScalarEvent,
)
from pipenv.vendor.ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode

if False:  # MYPY
    from typing import Any, Dict, Optional, List  # NOQA

__all__ = ['Composer', 'ComposerError']


class ComposerError(MarkedYAMLError):
    pass


class Composer:
    def __init__(self, loader: Any = None) -> None:
        self.loader = loader
        if self.loader is not None and getattr(self.loader, '_composer', None) is None:
            self.loader._composer = self
        self.anchors: Dict[Any, Any] = {}
        self.warn_double_anchors = True

    @property
    def parser(self) -> Any:
        if hasattr(self.loader, 'typ'):
            self.loader.parser
        return self.loader._parser

    @property
    def resolver(self) -> Any:
        # assert self.loader._resolver is not None
        if hasattr(self.loader, 'typ'):
            self.loader.resolver
        return self.loader._resolver

    def check_node(self) -> Any:
        # Drop the STREAM-START event.
        if self.parser.check_event(StreamStartEvent):
            self.parser.get_event()

        # If there are more documents available?
        return not self.parser.check_event(StreamEndEvent)

    def get_node(self) -> Any:
        # Get the root node of the next document.
        if not self.parser.check_event(StreamEndEvent):
            return self.compose_document()

    def get_single_node(self) -> Any:
        # Drop the STREAM-START event.
        self.parser.get_event()

        # Compose a document if the stream is not empty.
        document: Any = None
        if not self.parser.check_event(StreamEndEvent):
            document = self.compose_document()

        # Ensure that the stream contains no more documents.
        if not self.parser.check_event(StreamEndEvent):
            event = self.parser.get_event()
            raise ComposerError(
                'expected a single document in the stream',
                document.start_mark,
                'but found another document',
                event.start_mark,
            )

        # Drop the STREAM-END event.
        self.parser.get_event()

        return document

    def compose_document(self: Any) -> Any:
        # Drop the DOCUMENT-START event.
        self.parser.get_event()

        # Compose the root node.
        node = self.compose_node(None, None)

        # Drop the DOCUMENT-END event.
        self.parser.get_event()

        self.anchors = {}
        return node

    def return_alias(self, a: Any) -> Any:
        return a

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            alias = event.anchor
            if alias not in self.anchors:
                raise ComposerError(
                    None, None, f'found undefined alias {alias!r}', event.start_mark,
                )
            return self.return_alias(self.anchors[alias])
        event = self.parser.peek_event()
        anchor = event.anchor
        if anchor is not None:  # have an anchor
            if self.warn_double_anchors and anchor in self.anchors:
                ws = (
                    f'\nfound duplicate anchor {anchor!r}\n'
                    f'first occurrence {self.anchors[anchor].start_mark}\n'
                    f'second occurrence {event.start_mark}'
                )
                warnings.warn(ws, ReusedAnchorWarning, stacklevel=2)
        self.resolver.descend_resolver(parent, index)
        if self.parser.check_event(ScalarEvent):
            node = self.compose_scalar_node(anchor)
        elif self.parser.check_event(SequenceStartEvent):
            node = self.compose_sequence_node(anchor)
        elif self.parser.check_event(MappingStartEvent):
            node = self.compose_mapping_node(anchor)
        self.resolver.ascend_resolver()
        return node

    def compose_scalar_node(self, anchor: Any) -> Any:
        event = self.parser.get_event()
        tag = event.ctag
        if tag is None or str(tag) == '!':
            tag = self.resolver.resolve(ScalarNode, event.value, event.implicit)
            assert not isinstance(tag, str)
            # e.g tag.yaml.org,2002:str
        node = ScalarNode(
            tag,
            event.value,
            event.start_mark,
            event.end_mark,
            style=event.style,
            comment=event.comment,
            anchor=anchor,
        )
        if anchor is not None:
            self.anchors[anchor] = node
        return node

    def compose_sequence_node(self, anchor: Any) -> Any:
        start_event = self.parser.get_event()
        tag = start_event.ctag
        if tag is None or str(tag) == '!':
            tag = self.resolver.resolve(SequenceNode, None, start_event.implicit)
            assert not isinstance(tag, str)
        node = SequenceNode(
            tag,
            [],
            start_event.start_mark,
            None,
            flow_style=start_event.flow_style,
            comment=start_event.comment,
            anchor=anchor,
        )
        if anchor is not None:
            self.anchors[anchor] = node
        index = 0
        while not self.parser.check_event(SequenceEndEvent):
            node.value.append(self.compose_node(node, index))
            index += 1
        end_event = self.parser.get_event()
        if node.flow_style is True and end_event.comment is not None:
            if node.comment is not None:
                x = node.flow_style
                nprint(
                    f'Warning: unexpected end_event commment in sequence node {x}',
                )
            node.comment = end_event.comment
        node.end_mark = end_event.end_mark
        self.check_end_doc_comment(end_event, node)
        return node

    def compose_mapping_node(self, anchor: Any) -> Any:
        start_event = self.parser.get_event()
        tag = start_event.ctag
        if tag is None or str(tag) == '!':
            tag = self.resolver.resolve(MappingNode, None, start_event.implicit)
            assert not isinstance(tag, str)
        node = MappingNode(
            tag,
            [],
            start_event.start_mark,
            None,
            flow_style=start_event.flow_style,
            comment=start_event.comment,
            anchor=anchor,
        )
        if anchor is not None:
            self.anchors[anchor] = node
        while not self.parser.check_event(MappingEndEvent):
            # key_event = self.parser.peek_event()
            item_key = self.compose_node(node, None)
            # if item_key in node.value:
            #     raise ComposerError("while composing a mapping",
            #             start_event.start_mark,
            #             "found duplicate key", key_event.start_mark)
            item_value = self.compose_node(node, item_key)
            # node.value[item_key] = item_value
            node.value.append((item_key, item_value))
        end_event = self.parser.get_event()
        if node.flow_style is True and end_event.comment is not None:
            node.comment = end_event.comment
        node.end_mark = end_event.end_mark
        self.check_end_doc_comment(end_event, node)
        return node

    def check_end_doc_comment(self, end_event: Any, node: Any) -> None:
        if end_event.comment and end_event.comment[1]:
            # pre comments on an end_event, no following to move to
            if node.comment is None:
                node.comment = [None, None]
            assert not isinstance(node, ScalarEvent)
            # this is a post comment on a mapping node, add as third element
            # in the list
            node.comment.append(end_event.comment[1])
            end_event.comment[1] = None
