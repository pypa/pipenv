# coding: utf-8

# Emitter expects events obeying the following grammar:
# stream ::= STREAM-START document* STREAM-END
# document ::= DOCUMENT-START node DOCUMENT-END
# node ::= SCALAR | sequence | mapping
# sequence ::= SEQUENCE-START node* SEQUENCE-END
# mapping ::= MAPPING-START (node node)* MAPPING-END

import sys
from pipenv.vendor.ruamel.yaml.error import YAMLError, YAMLStreamError
from pipenv.vendor.ruamel.yaml.events import *  # NOQA

# fmt: off
from pipenv.vendor.ruamel.yaml.compat import nprint, dbg, DBG_EVENT, \
    check_anchorname_char, nprintf  # NOQA
# fmt: on


from typing import Any, Dict, List, Union, Text, Tuple, Optional  # NOQA
from pipenv.vendor.ruamel.yaml.compat import StreamType  # NOQA

__all__ = ['Emitter', 'EmitterError']


class EmitterError(YAMLError):
    pass


class ScalarAnalysis:
    def __init__(
        self,
        scalar: Any,
        empty: Any,
        multiline: Any,
        allow_flow_plain: bool,
        allow_block_plain: bool,
        allow_single_quoted: bool,
        allow_double_quoted: bool,
        allow_block: bool,
    ) -> None:
        self.scalar = scalar
        self.empty = empty
        self.multiline = multiline
        self.allow_flow_plain = allow_flow_plain
        self.allow_block_plain = allow_block_plain
        self.allow_single_quoted = allow_single_quoted
        self.allow_double_quoted = allow_double_quoted
        self.allow_block = allow_block


class Indents:
    # replacement for the list based stack of None/int
    def __init__(self) -> None:
        self.values: List[Tuple[Any, bool]] = []

    def append(self, val: Any, seq: Any) -> None:
        self.values.append((val, seq))

    def pop(self) -> Any:
        return self.values.pop()[0]

    def last_seq(self) -> bool:
        # return the seq(uence) value for the element added before the last one
        # in increase_indent()
        try:
            return self.values[-2][1]
        except IndexError:
            return False

    def seq_flow_align(
        self, seq_indent: int, column: int, pre_comment: Optional[bool] = False,
    ) -> int:
        # extra spaces because of dash
        # nprint('seq_flow_align', self.values, pre_comment)
        if len(self.values) < 2 or not self.values[-1][1]:
            if len(self.values) == 0 or not pre_comment:
                return 0
        base = self.values[-1][0] if self.values[-1][0] is not None else 0
        if pre_comment:
            return base + seq_indent  # type: ignore
            # return (len(self.values)) * seq_indent
        # -1 for the dash
        return base + seq_indent - column - 1  # type: ignore

    def __len__(self) -> int:
        return len(self.values)


class Emitter:
    # fmt: off
    DEFAULT_TAG_PREFIXES = {
        '!': '!',
        'tag:yaml.org,2002:': '!!',
        '!!': '!!',
    }
    # fmt: on

    MAX_SIMPLE_KEY_LENGTH = 128
    flow_seq_start = '['
    flow_seq_end = ']'
    flow_seq_separator = ','
    flow_map_start = '{'
    flow_map_end = '}'
    flow_map_separator = ','

    def __init__(
        self,
        stream: StreamType,
        canonical: Any = None,
        indent: Optional[int] = None,
        width: Optional[int] = None,
        allow_unicode: Optional[bool] = None,
        line_break: Any = None,
        block_seq_indent: Optional[int] = None,
        top_level_colon_align: Optional[bool] = None,
        prefix_colon: Any = None,
        brace_single_entry_mapping_in_flow_sequence: Optional[bool] = None,
        dumper: Any = None,
    ) -> None:
        # NOQA
        self.dumper = dumper
        if self.dumper is not None and getattr(self.dumper, '_emitter', None) is None:
            self.dumper._emitter = self
        self.stream = stream

        # Encoding can be overriden by STREAM-START.
        self.encoding: Optional[Text] = None
        self.allow_space_break = None

        # Emitter is a state machine with a stack of states to handle nested
        # structures.
        self.states: List[Any] = []
        self.state: Any = self.expect_stream_start

        # Current event and the event queue.
        self.events: List[Any] = []
        self.event: Any = None

        # The current indentation level and the stack of previous indents.
        self.indents = Indents()
        self.indent: Optional[int] = None

        # flow_context is an expanding/shrinking list consisting of '{' and '['
        # for each unclosed flow context. If empty list that means block context
        self.flow_context: List[Text] = []

        # Contexts.
        self.root_context = False
        self.sequence_context = False
        self.mapping_context = False
        self.simple_key_context = False

        # Characteristics of the last emitted character:
        #  - current position.
        #  - is it a whitespace?
        #  - is it an indention character
        #    (indentation space, '-', '?', or ':')?
        self.line = 0
        self.column = 0
        self.whitespace = True
        self.indention = True
        self.compact_seq_seq = True  # dash after dash
        self.compact_seq_map = True  # key after dash
        # self.compact_ms = False   # dash after key, only when excplicit key with ?
        self.no_newline: Optional[bool] = None  # set if directly after `- `

        # Whether the document requires an explicit document end indicator
        self.open_ended = False

        # colon handling
        self.colon = ':'
        self.prefixed_colon = self.colon if prefix_colon is None else prefix_colon + self.colon
        # single entry mappings in flow sequence
        self.brace_single_entry_mapping_in_flow_sequence = (
            brace_single_entry_mapping_in_flow_sequence  # NOQA
        )

        # Formatting details.
        self.canonical = canonical
        self.allow_unicode = allow_unicode
        # set to False to get "\Uxxxxxxxx" for non-basic unicode like emojis
        self.unicode_supplementary = sys.maxunicode > 0xFFFF
        self.sequence_dash_offset = block_seq_indent if block_seq_indent else 0
        self.top_level_colon_align = top_level_colon_align
        self.best_sequence_indent = 2
        self.requested_indent = indent  # specific for literal zero indent
        if indent and 1 < indent < 10:
            self.best_sequence_indent = indent
        self.best_map_indent = self.best_sequence_indent
        # if self.best_sequence_indent < self.sequence_dash_offset + 1:
        #     self.best_sequence_indent = self.sequence_dash_offset + 1
        self.best_width = 80
        if width and width > self.best_sequence_indent * 2:
            self.best_width = width
        self.best_line_break: Any = '\n'
        if line_break in ['\r', '\n', '\r\n']:
            self.best_line_break = line_break

        # Tag prefixes.
        self.tag_prefixes: Any = None

        # Prepared anchor and tag.
        self.prepared_anchor: Any = None
        self.prepared_tag: Any = None

        # Scalar analysis and style.
        self.analysis: Any = None
        self.style: Any = None

        self.scalar_after_indicator = True  # write a scalar on the same line as `---`

        self.alt_null = 'null'

    @property
    def stream(self) -> Any:
        try:
            return self._stream
        except AttributeError:
            raise YAMLStreamError('output stream needs to be specified')

    @stream.setter
    def stream(self, val: Any) -> None:
        if val is None:
            return
        if not hasattr(val, 'write'):
            raise YAMLStreamError('stream argument needs to have a write() method')
        self._stream = val

    @property
    def serializer(self) -> Any:
        try:
            if hasattr(self.dumper, 'typ'):
                return self.dumper.serializer
            return self.dumper._serializer
        except AttributeError:
            return self  # cyaml

    @property
    def flow_level(self) -> int:
        return len(self.flow_context)

    def dispose(self) -> None:
        # Reset the state attributes (to clear self-references)
        self.states = []
        self.state = None

    def emit(self, event: Any) -> None:
        if dbg(DBG_EVENT):
            nprint(event)
        self.events.append(event)
        while not self.need_more_events():
            self.event = self.events.pop(0)
            self.state()
            self.event = None

    # In some cases, we wait for a few next events before emitting.

    def need_more_events(self) -> bool:
        if not self.events:
            return True
        event = self.events[0]
        if isinstance(event, DocumentStartEvent):
            return self.need_events(1)
        elif isinstance(event, SequenceStartEvent):
            return self.need_events(2)
        elif isinstance(event, MappingStartEvent):
            return self.need_events(3)
        else:
            return False

    def need_events(self, count: int) -> bool:
        level = 0
        for event in self.events[1:]:
            if isinstance(event, (DocumentStartEvent, CollectionStartEvent)):
                level += 1
            elif isinstance(event, (DocumentEndEvent, CollectionEndEvent)):
                level -= 1
            elif isinstance(event, StreamEndEvent):
                level = -1
            if level < 0:
                return False
        return len(self.events) < count + 1

    def increase_indent(
        self, flow: bool = False, sequence: Optional[bool] = None, indentless: bool = False,
    ) -> None:
        self.indents.append(self.indent, sequence)
        if self.indent is None:  # top level
            if flow:
                # self.indent = self.best_sequence_indent if self.indents.last_seq() else \
                #              self.best_map_indent
                # self.indent = self.best_sequence_indent
                self.indent = self.requested_indent
            else:
                self.indent = 0
        elif not indentless:
            self.indent += (
                self.best_sequence_indent if self.indents.last_seq() else self.best_map_indent
            )
            # if self.indents.last_seq():
            #     if self.indent == 0: # top level block sequence
            #         self.indent = self.best_sequence_indent - self.sequence_dash_offset
            #     else:
            #         self.indent += self.best_sequence_indent
            # else:
            #     self.indent += self.best_map_indent

    # States.

    # Stream handlers.

    def expect_stream_start(self) -> None:
        if isinstance(self.event, StreamStartEvent):
            if self.event.encoding and not hasattr(self.stream, 'encoding'):
                self.encoding = self.event.encoding
            self.write_stream_start()
            self.state = self.expect_first_document_start
        else:
            raise EmitterError(f'expected StreamStartEvent, but got {self.event!s}')

    def expect_nothing(self) -> None:
        raise EmitterError(f'expected nothing, but got {self.event!s}')

    # Document handlers.

    def expect_first_document_start(self) -> Any:
        return self.expect_document_start(first=True)

    def expect_document_start(self, first: bool = False) -> None:
        if isinstance(self.event, DocumentStartEvent):
            if (self.event.version or self.event.tags) and self.open_ended:
                self.write_indicator('...', True)
                self.write_indent()
            if self.event.version:
                version_text = self.prepare_version(self.event.version)
                self.write_version_directive(version_text)
            self.tag_prefixes = self.DEFAULT_TAG_PREFIXES.copy()
            if self.event.tags:
                handles = sorted(self.event.tags.keys())
                for handle in handles:
                    prefix = self.event.tags[handle]
                    self.tag_prefixes[prefix] = handle
                    handle_text = self.prepare_tag_handle(handle)
                    prefix_text = self.prepare_tag_prefix(prefix)
                    self.write_tag_directive(handle_text, prefix_text)
            implicit = (
                first
                and not self.event.explicit
                and not self.canonical
                and not self.event.version
                and not self.event.tags
                and not self.check_empty_document()
            )
            if not implicit:
                self.write_indent()
                self.write_indicator('---', True)
                if self.canonical:
                    self.write_indent()
            self.state = self.expect_document_root
        elif isinstance(self.event, StreamEndEvent):
            if self.open_ended:
                self.write_indicator('...', True)
                self.write_indent()
            self.write_stream_end()
            self.state = self.expect_nothing
        else:
            raise EmitterError(f'expected DocumentStartEvent, but got {self.event!s}')

    def expect_document_end(self) -> None:
        if isinstance(self.event, DocumentEndEvent):
            self.write_indent()
            if self.event.explicit:
                self.write_indicator('...', True)
                self.write_indent()
            self.flush_stream()
            self.state = self.expect_document_start
        else:
            raise EmitterError(f'expected DocumentEndEvent, but got {self.event!s}')

    def expect_document_root(self) -> None:
        self.states.append(self.expect_document_end)
        self.expect_node(root=True)

    # Node handlers.

    def expect_node(
        self,
        root: bool = False,
        sequence: bool = False,
        mapping: bool = False,
        simple_key: bool = False,
    ) -> None:
        self.root_context = root
        self.sequence_context = sequence  # not used in PyYAML
        force_flow_indent = False
        self.mapping_context = mapping
        self.simple_key_context = simple_key
        if isinstance(self.event, AliasEvent):
            self.expect_alias()
        elif isinstance(self.event, (ScalarEvent, CollectionStartEvent)):
            if (
                self.process_anchor('&')
                and isinstance(self.event, ScalarEvent)
                and self.sequence_context
            ):
                self.sequence_context = False
            if (
                root
                and isinstance(self.event, ScalarEvent)
                and not self.scalar_after_indicator
            ):
                self.write_indent()
            self.process_tag()
            if isinstance(self.event, ScalarEvent):
                # nprint('@', self.indention, self.no_newline, self.column)
                self.expect_scalar()
            elif isinstance(self.event, SequenceStartEvent):
                # nprint('@', self.indention, self.no_newline, self.column)
                i2, n2 = self.indention, self.no_newline  # NOQA
                if self.event.comment:
                    if self.event.flow_style is False:
                        if self.write_post_comment(self.event):
                            self.indention = False
                            self.no_newline = True
                    if self.event.flow_style:
                        column = self.column
                    if self.write_pre_comment(self.event):
                        if self.event.flow_style:
                            # force_flow_indent = True
                            force_flow_indent = not self.indents.values[-1][1]
                        self.indention = i2
                        self.no_newline = not self.indention
                    if self.event.flow_style:
                        self.column = column
                if (
                    self.flow_level
                    or self.canonical
                    or self.event.flow_style
                    or self.check_empty_sequence()
                ):
                    self.expect_flow_sequence(force_flow_indent)
                else:
                    self.expect_block_sequence()
            elif isinstance(self.event, MappingStartEvent):
                if self.event.flow_style is False and self.event.comment:
                    self.write_post_comment(self.event)
                if self.event.comment and self.event.comment[1]:
                    self.write_pre_comment(self.event)
                    if self.event.flow_style and self.indents.values:
                        force_flow_indent = not self.indents.values[-1][1]
                if (
                    self.flow_level
                    or self.canonical
                    or self.event.flow_style
                    or self.check_empty_mapping()
                ):
                    self.expect_flow_mapping(
                        single=self.event.nr_items == 1, force_flow_indent=force_flow_indent,
                    )
                else:
                    self.expect_block_mapping()
        else:
            raise EmitterError('expected NodeEvent, but got {self.event!s}')

    def expect_alias(self) -> None:
        if self.event.anchor is None:
            raise EmitterError('anchor is not specified for alias')
        self.process_anchor('*')
        self.state = self.states.pop()

    def expect_scalar(self) -> None:
        self.increase_indent(flow=True)
        self.process_scalar()
        self.indent = self.indents.pop()
        self.state = self.states.pop()

    # Flow sequence handlers.

    def expect_flow_sequence(self, force_flow_indent: Optional[bool] = False) -> None:
        if force_flow_indent:
            self.increase_indent(flow=True, sequence=True)
        ind = self.indents.seq_flow_align(
            self.best_sequence_indent, self.column, force_flow_indent,
        )
        self.write_indicator(' ' * ind + self.flow_seq_start, True, whitespace=True)
        if not force_flow_indent:
            self.increase_indent(flow=True, sequence=True)
        self.flow_context.append('[')
        self.state = self.expect_first_flow_sequence_item

    def expect_first_flow_sequence_item(self) -> None:
        if isinstance(self.event, SequenceEndEvent):
            self.indent = self.indents.pop()
            popped = self.flow_context.pop()
            assert popped == '['
            self.write_indicator(self.flow_seq_end, False)
            if self.event.comment and self.event.comment[0]:
                # eol comment on empty flow sequence
                self.write_post_comment(self.event)
            elif self.flow_level == 0:
                self.write_line_break()
            self.state = self.states.pop()
        else:
            if self.canonical or self.column > self.best_width:
                self.write_indent()
            self.states.append(self.expect_flow_sequence_item)
            self.expect_node(sequence=True)

    def expect_flow_sequence_item(self) -> None:
        if isinstance(self.event, SequenceEndEvent):
            self.indent = self.indents.pop()
            popped = self.flow_context.pop()
            assert popped == '['
            if self.canonical:
                # ToDo: so-39595807, maybe add a space to the flow_seq_separator
                # and strip the last space, if space then indent, else do not
                # not sure that [1,2,3] is a valid YAML seq
                self.write_indicator(self.flow_seq_separator, False)
                self.write_indent()
            self.write_indicator(self.flow_seq_end, False)
            if self.event.comment and self.event.comment[0]:
                # eol comment on flow sequence
                self.write_post_comment(self.event)
            else:
                self.no_newline = False
            self.state = self.states.pop()
        else:
            self.write_indicator(self.flow_seq_separator, False)
            if self.canonical or self.column > self.best_width:
                self.write_indent()
            self.states.append(self.expect_flow_sequence_item)
            self.expect_node(sequence=True)

    # Flow mapping handlers.

    def expect_flow_mapping(
        self, single: Optional[bool] = False, force_flow_indent: Optional[bool] = False,
    ) -> None:
        if force_flow_indent:
            self.increase_indent(flow=True, sequence=False)
        ind = self.indents.seq_flow_align(
            self.best_sequence_indent, self.column, force_flow_indent,
        )
        map_init = self.flow_map_start
        if (
            single
            and self.flow_level
            and self.flow_context[-1] == '['
            and not self.canonical
            and not self.brace_single_entry_mapping_in_flow_sequence
        ):
            # single map item with flow context, no curly braces necessary
            map_init = ''
        self.write_indicator(' ' * ind + map_init, True, whitespace=True)
        self.flow_context.append(map_init)
        if not force_flow_indent:
            self.increase_indent(flow=True, sequence=False)
        self.state = self.expect_first_flow_mapping_key

    def expect_first_flow_mapping_key(self) -> None:
        if isinstance(self.event, MappingEndEvent):
            self.indent = self.indents.pop()
            popped = self.flow_context.pop()
            assert popped == '{'  # empty flow mapping
            self.write_indicator(self.flow_map_end, False)
            if self.event.comment and self.event.comment[0]:
                # eol comment on empty mapping
                self.write_post_comment(self.event)
            elif self.flow_level == 0:
                self.write_line_break()
            self.state = self.states.pop()
        else:
            if self.canonical or self.column > self.best_width:
                self.write_indent()
            if not self.canonical and self.check_simple_key():
                self.states.append(self.expect_flow_mapping_simple_value)
                self.expect_node(mapping=True, simple_key=True)
            else:
                self.write_indicator('?', True)
                self.states.append(self.expect_flow_mapping_value)
                self.expect_node(mapping=True)

    def expect_flow_mapping_key(self) -> None:
        if isinstance(self.event, MappingEndEvent):
            # if self.event.comment and self.event.comment[1]:
            #     self.write_pre_comment(self.event)
            self.indent = self.indents.pop()
            popped = self.flow_context.pop()
            assert popped in ['{', '']
            if self.canonical:
                self.write_indicator(self.flow_map_separator, False)
                self.write_indent()
            if popped != '':
                self.write_indicator(self.flow_map_end, False)
            if self.event.comment and self.event.comment[0]:
                # eol comment on flow mapping, never reached on empty mappings
                self.write_post_comment(self.event)
            else:
                self.no_newline = False
            self.state = self.states.pop()
        else:
            self.write_indicator(self.flow_map_separator, False)
            if self.canonical or self.column > self.best_width:
                self.write_indent()
            if not self.canonical and self.check_simple_key():
                self.states.append(self.expect_flow_mapping_simple_value)
                self.expect_node(mapping=True, simple_key=True)
            else:
                self.write_indicator('?', True)
                self.states.append(self.expect_flow_mapping_value)
                self.expect_node(mapping=True)

    def expect_flow_mapping_simple_value(self) -> None:
        self.write_indicator(self.prefixed_colon, False)
        self.states.append(self.expect_flow_mapping_key)
        self.expect_node(mapping=True)

    def expect_flow_mapping_value(self) -> None:
        if self.canonical or self.column > self.best_width:
            self.write_indent()
        self.write_indicator(self.prefixed_colon, True)
        self.states.append(self.expect_flow_mapping_key)
        self.expect_node(mapping=True)

    # Block sequence handlers.

    def expect_block_sequence(self) -> None:
        if self.mapping_context:
            indentless = not self.indention
        else:
            indentless = False
            if not self.compact_seq_seq and self.column != 0:
                self.write_line_break()
        self.increase_indent(flow=False, sequence=True, indentless=indentless)
        self.state = self.expect_first_block_sequence_item

    def expect_first_block_sequence_item(self) -> Any:
        return self.expect_block_sequence_item(first=True)

    def expect_block_sequence_item(self, first: bool = False) -> None:
        if not first and isinstance(self.event, SequenceEndEvent):
            if self.event.comment and self.event.comment[1]:
                # final comments on a block list e.g. empty line
                self.write_pre_comment(self.event)
            self.indent = self.indents.pop()
            self.state = self.states.pop()
            self.no_newline = False
        else:
            if self.event.comment and self.event.comment[1]:
                self.write_pre_comment(self.event)
            nonl = self.no_newline if self.column == 0 else False
            self.write_indent()
            ind = self.sequence_dash_offset  # if  len(self.indents) > 1 else 0
            self.write_indicator(' ' * ind + '-', True, indention=True)
            if nonl or self.sequence_dash_offset + 2 > self.best_sequence_indent:
                self.no_newline = True
            self.states.append(self.expect_block_sequence_item)
            self.expect_node(sequence=True)

    # Block mapping handlers.

    def expect_block_mapping(self) -> None:
        if not self.mapping_context and not (self.compact_seq_map or self.column == 0):
            self.write_line_break()
        self.increase_indent(flow=False, sequence=False)
        self.state = self.expect_first_block_mapping_key

    def expect_first_block_mapping_key(self) -> None:
        return self.expect_block_mapping_key(first=True)

    def expect_block_mapping_key(self, first: Any = False) -> None:
        if not first and isinstance(self.event, MappingEndEvent):
            if self.event.comment and self.event.comment[1]:
                # final comments from a doc
                self.write_pre_comment(self.event)
            self.indent = self.indents.pop()
            self.state = self.states.pop()
        else:
            if self.event.comment and self.event.comment[1]:
                # final comments from a doc
                self.write_pre_comment(self.event)
            self.write_indent()
            if self.check_simple_key():
                if not isinstance(
                    self.event, (SequenceStartEvent, MappingStartEvent),
                ):  # sequence keys
                    try:
                        if self.event.style == '?':
                            self.write_indicator('?', True, indention=True)
                    except AttributeError:  # aliases have no style
                        pass
                self.states.append(self.expect_block_mapping_simple_value)
                self.expect_node(mapping=True, simple_key=True)
                # test on style for alias in !!set
                if isinstance(self.event, AliasEvent) and not self.event.style == '?':
                    self.stream.write(' ')
            else:
                self.write_indicator('?', True, indention=True)
                self.states.append(self.expect_block_mapping_value)
                self.expect_node(mapping=True)

    def expect_block_mapping_simple_value(self) -> None:
        if getattr(self.event, 'style', None) != '?':
            # prefix = ''
            if self.indent == 0 and self.top_level_colon_align is not None:
                # write non-prefixed colon
                c = ' ' * (self.top_level_colon_align - self.column) + self.colon
            else:
                c = self.prefixed_colon
            self.write_indicator(c, False)
        self.states.append(self.expect_block_mapping_key)
        self.expect_node(mapping=True)

    def expect_block_mapping_value(self) -> None:
        self.write_indent()
        self.write_indicator(self.prefixed_colon, True, indention=True)
        self.states.append(self.expect_block_mapping_key)
        self.expect_node(mapping=True)

    # Checkers.

    def check_empty_sequence(self) -> bool:
        return (
            isinstance(self.event, SequenceStartEvent)
            and bool(self.events)
            and isinstance(self.events[0], SequenceEndEvent)
        )

    def check_empty_mapping(self) -> bool:
        return (
            isinstance(self.event, MappingStartEvent)
            and bool(self.events)
            and isinstance(self.events[0], MappingEndEvent)
        )

    def check_empty_document(self) -> bool:
        if not isinstance(self.event, DocumentStartEvent) or not self.events:
            return False
        event = self.events[0]
        return (
            isinstance(event, ScalarEvent)
            and event.anchor is None
            and event.tag is None
            and event.implicit
            and event.value == ""
        )

    def check_simple_key(self) -> bool:
        length = 0
        if isinstance(self.event, NodeEvent) and self.event.anchor is not None:
            if self.prepared_anchor is None:
                self.prepared_anchor = self.prepare_anchor(self.event.anchor)
            length += len(self.prepared_anchor)
        if (
            isinstance(self.event, (ScalarEvent, CollectionStartEvent))
            and self.event.tag is not None
        ):
            if self.prepared_tag is None:
                self.prepared_tag = self.prepare_tag(self.event.ctag)
            length += len(self.prepared_tag)
        if isinstance(self.event, ScalarEvent):
            if self.analysis is None:
                self.analysis = self.analyze_scalar(self.event.value)
            length += len(self.analysis.scalar)
        return length < self.MAX_SIMPLE_KEY_LENGTH and (
            isinstance(self.event, AliasEvent)
            or (isinstance(self.event, SequenceStartEvent) and self.event.flow_style is True)
            or (isinstance(self.event, MappingStartEvent) and self.event.flow_style is True)
            or (
                isinstance(self.event, ScalarEvent)
                # if there is an explicit style for an empty string, it is a simple key
                and not (self.analysis.empty and self.style and self.style not in '\'"')
                and not self.analysis.multiline
            )
            or self.check_empty_sequence()
            or self.check_empty_mapping()
        )

    # Anchor, Tag, and Scalar processors.

    def process_anchor(self, indicator: Any) -> bool:
        if self.event.anchor is None:
            self.prepared_anchor = None
            return False
        if self.prepared_anchor is None:
            self.prepared_anchor = self.prepare_anchor(self.event.anchor)
        if self.prepared_anchor:
            self.write_indicator(indicator + self.prepared_anchor, True)
            # issue 288
            self.no_newline = False
        self.prepared_anchor = None
        return True

    def process_tag(self) -> None:
        tag = self.event.tag
        if isinstance(self.event, ScalarEvent):
            if self.style is None:
                self.style = self.choose_scalar_style()
                if (
                    self.event.value == ''
                    and self.style == "'"
                    and tag == 'tag:yaml.org,2002:null'
                    and self.alt_null is not None
                ):
                    self.event.value = self.alt_null
                    self.analysis = None
                    self.style = self.choose_scalar_style()
            if (not self.canonical or tag is None) and (
                (self.style == "" and self.event.implicit[0])
                or (self.style != "" and self.event.implicit[1])
            ):
                self.prepared_tag = None
                return
            if self.event.implicit[0] and tag is None:
                tag = '!'
                self.prepared_tag = None
        else:
            if (not self.canonical or tag is None) and self.event.implicit:
                self.prepared_tag = None
                return
        if tag is None:
            raise EmitterError('tag is not specified')
        if self.prepared_tag is None:
            self.prepared_tag = self.prepare_tag(self.event.ctag)
        if self.prepared_tag:
            self.write_indicator(self.prepared_tag, True)
            if (
                self.sequence_context
                and not self.flow_level
                and isinstance(self.event, ScalarEvent)
            ):
                self.no_newline = True
        self.prepared_tag = None

    def choose_scalar_style(self) -> Any:
        # issue 449 needs this otherwise emits single quoted empty string
        if self.event.value == '' and self.event.ctag.handle == '!!':
            return None
        if self.analysis is None:
            self.analysis = self.analyze_scalar(self.event.value)
        if self.event.style == '"' or self.canonical:
            return '"'
        if (not self.event.style or self.event.style == '?') and (
            self.event.implicit[0] or not self.event.implicit[2]
        ):
            if not (
                self.simple_key_context and (self.analysis.empty or self.analysis.multiline)
            ) and (
                self.flow_level
                and self.analysis.allow_flow_plain
                or (not self.flow_level and self.analysis.allow_block_plain)
            ):
                return ""
        self.analysis.allow_block = True
        if self.event.style and self.event.style in '|>':
            if (
                not self.flow_level
                and not self.simple_key_context
                and self.analysis.allow_block
            ):
                return self.event.style
        if not self.event.style and self.analysis.allow_double_quoted:
            if "'" in self.event.value or '\n' in self.event.value:
                return '"'
        if not self.event.style or self.event.style == "'":
            if self.analysis.allow_single_quoted and not (
                self.simple_key_context and self.analysis.multiline
            ):
                return "'"
        return '"'

    def process_scalar(self) -> None:
        if self.analysis is None:
            self.analysis = self.analyze_scalar(self.event.value)
        if self.style is None:
            self.style = self.choose_scalar_style()
        split = not self.simple_key_context
        # if self.analysis.multiline and split    \
        #         and (not self.style or self.style in '\'\"'):
        #     self.write_indent()
        # nprint('xx', self.sequence_context, self.flow_level)
        if self.sequence_context and not self.flow_level:
            self.write_indent()
        if self.style == '"':
            self.write_double_quoted(self.analysis.scalar, split)
        elif self.style == "'":
            self.write_single_quoted(self.analysis.scalar, split)
        elif self.style == '>':
            try:
                cmx = self.event.comment[1][0]
            except (IndexError, TypeError):
                cmx = ""
            self.write_folded(self.analysis.scalar, cmx)
            if (
                self.event.comment
                and self.event.comment[0]
                and self.event.comment[0].column >= self.indent
            ):
                # comment following a folded scalar must dedent (issue 376)
                self.event.comment[0].column = self.indent - 1  # type: ignore
        elif self.style == '|':
            # self.write_literal(self.analysis.scalar, self.event.comment)
            try:
                cmx = self.event.comment[1][0]
            except (IndexError, TypeError):
                cmx = ""
            self.write_literal(self.analysis.scalar, cmx)
            if (
                self.event.comment
                and self.event.comment[0]
                and self.event.comment[0].column >= self.indent
            ):
                # comment following a literal scalar must dedent (issue 376)
                self.event.comment[0].column = self.indent - 1  # type: ignore
        else:
            self.write_plain(self.analysis.scalar, split)
        self.analysis = None
        self.style = None
        if self.event.comment:
            self.write_post_comment(self.event)

    # Analyzers.

    def prepare_version(self, version: Any) -> Any:
        major, minor = version
        if major != 1:
            raise EmitterError(f'unsupported YAML version: {major:d}.{minor:d}')
        return f'{major:d}.{minor:d}'

    def prepare_tag_handle(self, handle: Any) -> Any:
        if not handle:
            raise EmitterError('tag handle must not be empty')
        if handle[0] != '!' or handle[-1] != '!':
            raise EmitterError(f"tag handle must start and end with '!': {handle!r}")
        for ch in handle[1:-1]:
            if not ('0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or ch in '-_'):
                raise EmitterError(f'invalid character {ch!r} in the tag handle: {handle!r}')
        return handle

    def prepare_tag_prefix(self, prefix: Any) -> Any:
        if not prefix:
            raise EmitterError('tag prefix must not be empty')
        chunks: List[Any] = []
        start = end = 0
        if prefix[0] == '!':
            end = 1
        ch_set = "-;/?:@&=+$,_.~*'()[]"
        if self.dumper:
            version = getattr(self.dumper, 'version', (1, 2))
            if version is None or version >= (1, 2):
                ch_set += '#'
        while end < len(prefix):
            ch = prefix[end]
            if '0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or ch in ch_set:
                end += 1
            else:
                if start < end:
                    chunks.append(prefix[start:end])
                start = end = end + 1
                data = ch
                for ch in data:
                    chunks.append(f'%{ord(ch):02X}')
        if start < end:
            chunks.append(prefix[start:end])
        return "".join(chunks)

    def prepare_tag(self, tag: Any) -> Any:
        if not tag:
            raise EmitterError('tag must not be empty')
        tag = str(tag)
        if tag == '!' or tag == '!!':
            return tag
        handle = None
        suffix = tag
        prefixes = sorted(self.tag_prefixes.keys())
        for prefix in prefixes:
            if tag.startswith(prefix) and (prefix == '!' or len(prefix) < len(tag)):
                handle = self.tag_prefixes[prefix]
                suffix = tag[len(prefix) :]
        chunks: List[Any] = []
        start = end = 0
        ch_set = "-;/?:@&=+$,_.~*'()[]"
        if self.dumper:
            version = getattr(self.dumper, 'version', (1, 2))
            if version is None or version >= (1, 2):
                ch_set += '#'
        while end < len(suffix):
            ch = suffix[end]
            if (
                '0' <= ch <= '9'
                or 'A' <= ch <= 'Z'
                or 'a' <= ch <= 'z'
                or ch in ch_set
                or (ch == '!' and handle != '!')
            ):
                end += 1
            else:
                if start < end:
                    chunks.append(suffix[start:end])
                start = end = end + 1
                data = ch
                for ch in data:
                    chunks.append(f'%{ord(ch):02X}')
        if start < end:
            chunks.append(suffix[start:end])
        suffix_text = "".join(chunks)
        if handle:
            return f'{handle!s}{suffix_text!s}'
        else:
            return f'!<{suffix_text!s}>'

    def prepare_anchor(self, anchor: Any) -> Any:
        if not anchor:
            raise EmitterError('anchor must not be empty')
        for ch in anchor:
            if not check_anchorname_char(ch):
                raise EmitterError(f'invalid character {ch!r} in the anchor: {anchor!r}')
        return anchor

    def analyze_scalar(self, scalar: Any) -> Any:
        # Empty scalar is a special case.
        if not scalar:
            return ScalarAnalysis(
                scalar=scalar,
                empty=True,
                multiline=False,
                allow_flow_plain=False,
                allow_block_plain=True,
                allow_single_quoted=True,
                allow_double_quoted=True,
                allow_block=False,
            )

        # Indicators and special characters.
        block_indicators = False
        flow_indicators = False
        line_breaks = False
        special_characters = False

        # Important whitespace combinations.
        leading_space = False
        leading_break = False
        trailing_space = False
        trailing_break = False
        break_space = False
        space_break = False

        # Check document indicators.
        if scalar.startswith('---') or scalar.startswith('...'):
            block_indicators = True
            flow_indicators = True

        # First character or preceded by a whitespace.
        preceeded_by_whitespace = True

        # Last character or followed by a whitespace.
        followed_by_whitespace = len(scalar) == 1 or scalar[1] in '\0 \t\r\n\x85\u2028\u2029'

        # The previous character is a space.
        previous_space = False

        # The previous character is a break.
        previous_break = False

        index = 0
        while index < len(scalar):
            ch = scalar[index]

            # Check for indicators.
            if index == 0:
                # Leading indicators are special characters.
                if ch in '#,[]{}&*!|>\'"%@`':
                    flow_indicators = True
                    block_indicators = True
                if ch in '?:':  # ToDo
                    if self.serializer.use_version == (1, 1):
                        flow_indicators = True
                    elif len(scalar) == 1:  # single character
                        flow_indicators = True
                    if followed_by_whitespace:
                        block_indicators = True
                if ch == '-' and followed_by_whitespace:
                    flow_indicators = True
                    block_indicators = True
            else:
                # Some indicators cannot appear within a scalar as well.
                if ch in ',[]{}':  # http://yaml.org/spec/1.2/spec.html#id2788859
                    flow_indicators = True
                if ch == '?' and self.serializer.use_version == (1, 1):
                    flow_indicators = True
                if ch == ':':
                    if followed_by_whitespace:
                        flow_indicators = True
                        block_indicators = True
                if ch == '#' and preceeded_by_whitespace:
                    flow_indicators = True
                    block_indicators = True

            # Check for line breaks, special, and unicode characters.
            if ch in '\n\x85\u2028\u2029':
                line_breaks = True
            if not (ch == '\n' or '\x20' <= ch <= '\x7E'):
                if (
                    ch == '\x85'
                    or '\xA0' <= ch <= '\uD7FF'
                    or '\uE000' <= ch <= '\uFFFD'
                    or (self.unicode_supplementary and ('\U00010000' <= ch <= '\U0010FFFF'))
                ) and ch != '\uFEFF':
                    # unicode_characters = True
                    if not self.allow_unicode:
                        special_characters = True
                else:
                    special_characters = True

            # Detect important whitespace combinations.
            if ch == ' ':
                if index == 0:
                    leading_space = True
                if index == len(scalar) - 1:
                    trailing_space = True
                if previous_break:
                    break_space = True
                previous_space = True
                previous_break = False
            elif ch in '\n\x85\u2028\u2029':
                if index == 0:
                    leading_break = True
                if index == len(scalar) - 1:
                    trailing_break = True
                if previous_space:
                    space_break = True
                previous_space = False
                previous_break = True
            else:
                previous_space = False
                previous_break = False

            # Prepare for the next character.
            index += 1
            preceeded_by_whitespace = ch in '\0 \t\r\n\x85\u2028\u2029'
            followed_by_whitespace = (
                index + 1 >= len(scalar) or scalar[index + 1] in '\0 \t\r\n\x85\u2028\u2029'
            )

        # Let's decide what styles are allowed.
        allow_flow_plain = True
        allow_block_plain = True
        allow_single_quoted = True
        allow_double_quoted = True
        allow_block = True

        # Leading and trailing whitespaces are bad for plain scalars.
        if leading_space or leading_break or trailing_space or trailing_break:
            allow_flow_plain = allow_block_plain = False

        # We do not permit trailing spaces for block scalars.
        if trailing_space:
            allow_block = False

        # Spaces at the beginning of a new line are only acceptable for block
        # scalars.
        if break_space:
            allow_flow_plain = allow_block_plain = allow_single_quoted = False

        # Spaces followed by breaks, as well as special character are only
        # allowed for double quoted scalars.
        if special_characters:
            allow_flow_plain = allow_block_plain = allow_single_quoted = allow_block = False
        elif space_break:
            allow_flow_plain = allow_block_plain = allow_single_quoted = False
            if not self.allow_space_break:
                allow_block = False

        # Although the plain scalar writer supports breaks, we never emit
        # multiline plain scalars.
        if line_breaks:
            allow_flow_plain = allow_block_plain = False

        # Flow indicators are forbidden for flow plain scalars.
        if flow_indicators:
            allow_flow_plain = False

        # Block indicators are forbidden for block plain scalars.
        if block_indicators:
            allow_block_plain = False

        return ScalarAnalysis(
            scalar=scalar,
            empty=False,
            multiline=line_breaks,
            allow_flow_plain=allow_flow_plain,
            allow_block_plain=allow_block_plain,
            allow_single_quoted=allow_single_quoted,
            allow_double_quoted=allow_double_quoted,
            allow_block=allow_block,
        )

    # Writers.

    def flush_stream(self) -> None:
        if hasattr(self.stream, 'flush'):
            self.stream.flush()

    def write_stream_start(self) -> None:
        # Write BOM if needed.
        if self.encoding and self.encoding.startswith('utf-16'):
            self.stream.write('\uFEFF'.encode(self.encoding))

    def write_stream_end(self) -> None:
        self.flush_stream()

    def write_indicator(
        self,
        indicator: Any,
        need_whitespace: Any,
        whitespace: bool = False,
        indention: bool = False,
    ) -> None:
        if self.whitespace or not need_whitespace:
            data = indicator
        else:
            data = ' ' + indicator
        self.whitespace = whitespace
        self.indention = self.indention and indention
        self.column += len(data)
        self.open_ended = False
        if bool(self.encoding):
            data = data.encode(self.encoding)
        self.stream.write(data)

    def write_indent(self) -> None:
        indent = self.indent or 0
        if (
            not self.indention
            or self.column > indent
            or (self.column == indent and not self.whitespace)
        ):
            if bool(self.no_newline):
                self.no_newline = False
            else:
                self.write_line_break()
        if self.column < indent:
            self.whitespace = True
            data = ' ' * (indent - self.column)
            self.column = indent
            if self.encoding:
                data = data.encode(self.encoding)  # type: ignore
            self.stream.write(data)

    def write_line_break(self, data: Any = None) -> None:
        if data is None:
            data = self.best_line_break
        self.whitespace = True
        self.indention = True
        self.line += 1
        self.column = 0
        if bool(self.encoding):
            data = data.encode(self.encoding)
        self.stream.write(data)

    def write_version_directive(self, version_text: Any) -> None:
        data: Any = f'%YAML {version_text!s}'
        if self.encoding:
            data = data.encode(self.encoding)
        self.stream.write(data)
        self.write_line_break()

    def write_tag_directive(self, handle_text: Any, prefix_text: Any) -> None:
        data: Any = f'%TAG {handle_text!s} {prefix_text!s}'
        if self.encoding:
            data = data.encode(self.encoding)
        self.stream.write(data)
        self.write_line_break()

    # Scalar streams.

    def write_single_quoted(self, text: Any, split: Any = True) -> None:
        if self.root_context:
            if self.requested_indent is not None:
                self.write_line_break()
                if self.requested_indent != 0:
                    self.write_indent()
        self.write_indicator("'", True)
        spaces = False
        breaks = False
        start = end = 0
        while end <= len(text):
            ch = None
            if end < len(text):
                ch = text[end]
            if spaces:
                if ch is None or ch != ' ':
                    if (
                        start + 1 == end
                        and self.column > self.best_width
                        and split
                        and start != 0
                        and end != len(text)
                    ):
                        self.write_indent()
                    else:
                        data = text[start:end]
                        self.column += len(data)
                        if bool(self.encoding):
                            data = data.encode(self.encoding)
                        self.stream.write(data)
                    start = end
            elif breaks:
                if ch is None or ch not in '\n\x85\u2028\u2029':
                    if text[start] == '\n':
                        self.write_line_break()
                    for br in text[start:end]:
                        if br == '\n':
                            self.write_line_break()
                        else:
                            self.write_line_break(br)
                    self.write_indent()
                    start = end
            else:
                if ch is None or ch in ' \n\x85\u2028\u2029' or ch == "'":
                    if start < end:
                        data = text[start:end]
                        self.column += len(data)
                        if bool(self.encoding):
                            data = data.encode(self.encoding)
                        self.stream.write(data)
                        start = end
            if ch == "'":
                data = "''"
                self.column += 2
                if bool(self.encoding):
                    data = data.encode(self.encoding)
                self.stream.write(data)
                start = end + 1
            if ch is not None:
                spaces = ch == ' '
                breaks = ch in '\n\x85\u2028\u2029'
            end += 1
        self.write_indicator("'", False)

    ESCAPE_REPLACEMENTS = {
        '\0': '0',
        '\x07': 'a',
        '\x08': 'b',
        '\x09': 't',
        '\x0A': 'n',
        '\x0B': 'v',
        '\x0C': 'f',
        '\x0D': 'r',
        '\x1B': 'e',
        '"': '"',
        '\\': '\\',
        '\x85': 'N',
        '\xA0': '_',
        '\u2028': 'L',
        '\u2029': 'P',
    }

    def write_double_quoted(self, text: Any, split: Any = True) -> None:
        if self.root_context:
            if self.requested_indent is not None:
                self.write_line_break()
                if self.requested_indent != 0:
                    self.write_indent()
        self.write_indicator('"', True)
        start = end = 0
        while end <= len(text):
            ch = None
            if end < len(text):
                ch = text[end]
            if (
                ch is None
                or ch in '"\\\x85\u2028\u2029\uFEFF'
                or not (
                    '\x20' <= ch <= '\x7E'
                    or (
                        self.allow_unicode
                        and (
                            ('\xA0' <= ch <= '\uD7FF')
                            or ('\uE000' <= ch <= '\uFFFD')
                            or ('\U00010000' <= ch <= '\U0010FFFF')
                        )
                    )
                )
            ):
                if start < end:
                    data = text[start:end]
                    self.column += len(data)
                    if bool(self.encoding):
                        data = data.encode(self.encoding)
                    self.stream.write(data)
                    start = end
                if ch is not None:
                    if ch in self.ESCAPE_REPLACEMENTS:
                        data = '\\' + self.ESCAPE_REPLACEMENTS[ch]
                    elif ch <= '\xFF':
                        data = '\\x%02X' % ord(ch)
                    elif ch <= '\uFFFF':
                        data = '\\u%04X' % ord(ch)
                    else:
                        data = '\\U%08X' % ord(ch)
                    self.column += len(data)
                    if bool(self.encoding):
                        data = data.encode(self.encoding)
                    self.stream.write(data)
                    start = end + 1
            if (
                0 < end < len(text) - 1
                and (ch == ' ' or start >= end)
                and self.column + (end - start) > self.best_width
                and split
            ):
                # SO https://stackoverflow.com/a/75634614/1307905
                # data = text[start:end] + u'\\'  # <<< replaced with following six lines
                need_backquote = True
                if len(text) > end:
                    try:
                        space_pos = text.index(' ', end)
                        if (
                            '"' not in text[end:space_pos]
                            and "'" not in text[end:space_pos]
                            and text[space_pos + 1] != ' '
                            and text[end - 1 : end + 1] != '  '
                        ):
                            need_backquote = False
                    except (ValueError, IndexError):
                        pass
                data = text[start:end] + ('\\' if need_backquote else '')
                if start < end:
                    start = end
                self.column += len(data)
                if bool(self.encoding):
                    data = data.encode(self.encoding)
                self.stream.write(data)
                self.write_indent()
                self.whitespace = False
                self.indention = False
                if text[start] == ' ':
                    if not need_backquote:
                        # remove leading space it will load from the newline
                        start += 1
                    # data = u'\\'    # <<< replaced with following line
                    data = '\\' if need_backquote else ''
                    self.column += len(data)
                    if bool(self.encoding):
                        data = data.encode(self.encoding)
                    self.stream.write(data)
            end += 1
        self.write_indicator('"', False)

    def determine_block_hints(self, text: Any) -> Any:
        indent = 0
        indicator = ''
        hints = ''
        if text:
            if text[0] in ' \n\x85\u2028\u2029':
                indent = 2
                hints += str(indent)
            elif self.root_context:
                for end in ['\n---', '\n...']:
                    pos = 0
                    while True:
                        pos = text.find(end, pos)
                        if pos == -1:
                            break
                        try:
                            if text[pos + 4] in ' \r\n':
                                break
                        except IndexError:
                            pass
                        pos += 1
                    if pos > -1:
                        break
                if pos > 0:
                    indent = 2
            if text[-1] not in '\n\x85\u2028\u2029':
                indicator = '-'
            elif len(text) == 1 or text[-2] in '\n\x85\u2028\u2029':
                indicator = '+'
        hints += indicator
        return hints, indent, indicator

    def write_folded(self, text: Any, comment: Any) -> None:
        hints, _indent, _indicator = self.determine_block_hints(text)
        if not isinstance(comment, str):
            comment = ''
        self.write_indicator('>' + hints + comment, True)
        if _indicator == '+':
            self.open_ended = True
        self.write_line_break()
        leading_space = True
        spaces = False
        breaks = True
        start = end = 0
        while end <= len(text):
            ch = None
            if end < len(text):
                ch = text[end]
            if breaks:
                if ch is None or ch not in '\n\x85\u2028\u2029\a':
                    if (
                        not leading_space
                        and ch is not None
                        and ch != ' '
                        and text[start] == '\n'
                    ):
                        self.write_line_break()
                    leading_space = ch == ' '
                    for br in text[start:end]:
                        if br == '\n':
                            self.write_line_break()
                        else:
                            self.write_line_break(br)
                    if ch is not None:
                        self.write_indent()
                    start = end
            elif spaces:
                if ch != ' ':
                    if start + 1 == end and self.column > self.best_width:
                        self.write_indent()
                    else:
                        data = text[start:end]
                        self.column += len(data)
                        if bool(self.encoding):
                            data = data.encode(self.encoding)
                        self.stream.write(data)
                    start = end
            else:
                if ch is None or ch in ' \n\x85\u2028\u2029\a':
                    data = text[start:end]
                    self.column += len(data)
                    if bool(self.encoding):
                        data = data.encode(self.encoding)
                    self.stream.write(data)
                    if ch == '\a':
                        if end < (len(text) - 1) and not text[end + 2].isspace():
                            self.write_line_break()
                            self.write_indent()
                            end += 2  # \a and the space that is inserted on the fold
                        else:
                            raise EmitterError('unexcpected fold indicator \\a before space')
                    if ch is None:
                        self.write_line_break()
                    start = end
            if ch is not None:
                breaks = ch in '\n\x85\u2028\u2029'
                spaces = ch == ' '
            end += 1

    def write_literal(self, text: Any, comment: Any = None) -> None:
        hints, _indent, _indicator = self.determine_block_hints(text)
        # if comment is not None:
        #    try:
        #        hints += comment[1][0]
        #    except (TypeError, IndexError) as e:
        #        pass
        if not isinstance(comment, str):
            comment = ''
        self.write_indicator('|' + hints + comment, True)
        # try:
        #    nprintf('selfev', comment)
        #    cmx = comment[1][0]
        #    if cmx:
        #        self.stream.write(cmx)
        # except (TypeError, IndexError) as e:
        #    pass
        if _indicator == '+':
            self.open_ended = True
        self.write_line_break()
        breaks = True
        start = end = 0
        while end <= len(text):
            ch = None
            if end < len(text):
                ch = text[end]
            if breaks:
                if ch is None or ch not in '\n\x85\u2028\u2029':
                    for br in text[start:end]:
                        if br == '\n':
                            self.write_line_break()
                        else:
                            self.write_line_break(br)
                    if ch is not None:
                        if self.root_context:
                            idnx = self.indent if self.indent is not None else 0
                            self.stream.write(' ' * (_indent + idnx))
                        else:
                            self.write_indent()
                    start = end
            else:
                if ch is None or ch in '\n\x85\u2028\u2029':
                    data = text[start:end]
                    if bool(self.encoding):
                        data = data.encode(self.encoding)
                    self.stream.write(data)
                    if ch is None:
                        self.write_line_break()
                    start = end
            if ch is not None:
                breaks = ch in '\n\x85\u2028\u2029'
            end += 1

    def write_plain(self, text: Any, split: Any = True) -> None:
        if self.root_context:
            if self.requested_indent is not None:
                self.write_line_break()
                if self.requested_indent != 0:
                    self.write_indent()
            else:
                self.open_ended = True
        if not text:
            return
        if not self.whitespace:
            data = ' '
            self.column += len(data)
            if self.encoding:
                data = data.encode(self.encoding)  # type: ignore
            self.stream.write(data)
        self.whitespace = False
        self.indention = False
        spaces = False
        breaks = False
        start = end = 0
        while end <= len(text):
            ch = None
            if end < len(text):
                ch = text[end]
            if spaces:
                if ch != ' ':
                    if start + 1 == end and self.column > self.best_width and split:
                        self.write_indent()
                        self.whitespace = False
                        self.indention = False
                    else:
                        data = text[start:end]
                        self.column += len(data)
                        if self.encoding:
                            data = data.encode(self.encoding)  # type: ignore
                        self.stream.write(data)
                    start = end
            elif breaks:
                if ch not in '\n\x85\u2028\u2029':  # type: ignore
                    if text[start] == '\n':
                        self.write_line_break()
                    for br in text[start:end]:
                        if br == '\n':
                            self.write_line_break()
                        else:
                            self.write_line_break(br)
                    self.write_indent()
                    self.whitespace = False
                    self.indention = False
                    start = end
            else:
                if ch is None or ch in ' \n\x85\u2028\u2029':
                    data = text[start:end]
                    if (
                        len(data) > self.best_width
                        and self.indent is not None
                        and self.column > self.indent
                    ):
                        # words longer than line length get a line of their own
                        self.write_indent()
                    self.column += len(data)
                    if self.encoding:
                        data = data.encode(self.encoding)  # type: ignore
                    try:
                        self.stream.write(data)
                    except:  # NOQA
                        sys.stdout.write(repr(data) + '\n')
                        raise
                    start = end
            if ch is not None:
                spaces = ch == ' '
                breaks = ch in '\n\x85\u2028\u2029'
            end += 1

    def write_comment(self, comment: Any, pre: bool = False) -> None:
        value = comment.value
        # nprintf(f'{self.column:02d} {comment.start_mark.column:02d} {value!r}')
        if not pre and value[-1] == '\n':
            value = value[:-1]
        try:
            # get original column position
            col = comment.start_mark.column
            if comment.value and comment.value.startswith('\n'):
                # never inject extra spaces if the comment starts with a newline
                # and not a real comment (e.g. if you have an empty line following a key-value
                col = self.column
            elif col < self.column + 1:
                ValueError
        except ValueError:
            col = self.column + 1
        # nprint('post_comment', self.line, self.column, value)
        try:
            # at least one space if the current column >= the start column of the comment
            # but not at the start of a line
            nr_spaces = col - self.column
            if self.column and value.strip() and nr_spaces < 1 and value[0] != '\n':
                nr_spaces = 1
            value = ' ' * nr_spaces + value
            try:
                if bool(self.encoding):
                    value = value.encode(self.encoding)
            except UnicodeDecodeError:
                pass
            self.stream.write(value)
        except TypeError:
            raise
        if not pre:
            self.write_line_break()

    def write_pre_comment(self, event: Any) -> bool:
        comments = event.comment[1]
        if comments is None:
            return False
        try:
            start_events = (MappingStartEvent, SequenceStartEvent)
            for comment in comments:
                if isinstance(event, start_events) and getattr(comment, 'pre_done', None):
                    continue
                if self.column != 0:
                    self.write_line_break()
                self.write_comment(comment, pre=True)
                if isinstance(event, start_events):
                    comment.pre_done = True
        except TypeError:
            sys.stdout.write(f'eventtt {type(event)} {event}')
            raise
        return True

    def write_post_comment(self, event: Any) -> bool:
        if self.event.comment[0] is None:
            return False
        comment = event.comment[0]
        self.write_comment(comment)
        return True


class RoundTripEmitter(Emitter):
    def prepare_tag(self, ctag: Any) -> Any:
        if not ctag:
            raise EmitterError('tag must not be empty')
        tag = str(ctag)
        # print('handling', repr(tag))
        if tag == '!' or tag == '!!':
            return tag
        handle = ctag.handle
        suffix = ctag.suffix
        prefixes = sorted(self.tag_prefixes.keys())
        # print('handling', repr(tag), repr(suffix), repr(handle))
        if handle is None:
            for prefix in prefixes:
                if tag.startswith(prefix) and (prefix == '!' or len(prefix) < len(tag)):
                    handle = self.tag_prefixes[prefix]
                    suffix = suffix[len(prefix) :]
        if handle:
            return f'{handle!s}{suffix!s}'
        else:
            return f'!<{suffix!s}>'
