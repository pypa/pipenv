# coding: utf-8

# Scanner produces tokens of the following types:
# STREAM-START
# STREAM-END
# DIRECTIVE(name, value)
# DOCUMENT-START
# DOCUMENT-END
# BLOCK-SEQUENCE-START
# BLOCK-MAPPING-START
# BLOCK-END
# FLOW-SEQUENCE-START
# FLOW-MAPPING-START
# FLOW-SEQUENCE-END
# FLOW-MAPPING-END
# BLOCK-ENTRY
# FLOW-ENTRY
# KEY
# VALUE
# ALIAS(value)
# ANCHOR(value)
# TAG(value)
# SCALAR(value, plain, style)
#
# RoundTripScanner
# COMMENT(value)
#
# Read comments in the Scanner code for more details.
#

import inspect
from pipenv.vendor.ruamel.yaml.error import MarkedYAMLError, CommentMark  # NOQA
from pipenv.vendor.ruamel.yaml.tokens import *  # NOQA
from pipenv.vendor.ruamel.yaml.compat import check_anchorname_char, nprint, nprintf  # NOQA

from typing import Any, Dict, Optional, List, Union, Text  # NOQA
from pipenv.vendor.ruamel.yaml.compat import VersionType  # NOQA

__all__ = ['Scanner', 'RoundTripScanner', 'ScannerError']


_THE_END = '\n\0\r\x85\u2028\u2029'
_THE_END_SPACE_TAB = ' \n\0\t\r\x85\u2028\u2029'
_SPACE_TAB = ' \t'


def xprintf(*args: Any, **kw: Any) -> Any:
    return nprintf(*args, **kw)
    pass


class ScannerError(MarkedYAMLError):
    pass


class SimpleKey:
    # See below simple keys treatment.

    def __init__(
        self, token_number: Any, required: Any, index: int, line: int, column: int, mark: Any,
    ) -> None:
        self.token_number = token_number
        self.required = required
        self.index = index
        self.line = line
        self.column = column
        self.mark = mark


class Scanner:
    def __init__(self, loader: Any = None) -> None:
        """Initialize the scanner."""
        # It is assumed that Scanner and Reader will have a common descendant.
        # Reader do the dirty work of checking for BOM and converting the
        # input data to Unicode. It also adds NUL to the end.
        #
        # Reader supports the following methods
        #   self.peek(i=0)    # peek the next i-th character
        #   self.prefix(l=1)  # peek the next l characters
        #   self.forward(l=1) # read the next l characters and move the pointer

        self.loader = loader
        if self.loader is not None and getattr(self.loader, '_scanner', None) is None:
            self.loader._scanner = self
        self.reset_scanner()
        self.first_time = False
        self.yaml_version: Any = None

    @property
    def flow_level(self) -> int:
        return len(self.flow_context)

    def reset_scanner(self) -> None:
        # Had we reached the end of the stream?
        self.done = False

        # flow_context is an expanding/shrinking list consisting of '{' and '['
        # for each unclosed flow context. If empty list that means block context
        self.flow_context: List[Text] = []

        # List of processed tokens that are not yet emitted.
        self.tokens: List[Any] = []

        # Add the STREAM-START token.
        self.fetch_stream_start()

        # Number of tokens that were emitted through the `get_token` method.
        self.tokens_taken = 0

        # The current indentation level.
        self.indent = -1

        # Past indentation levels.
        self.indents: List[int] = []

        # Variables related to simple keys treatment.

        # A simple key is a key that is not denoted by the '?' indicator.
        # Example of simple keys:
        #   ---
        #   block simple key: value
        #   ? not a simple key:
        #   : { flow simple key: value }
        # We emit the KEY token before all keys, so when we find a potential
        # simple key, we try to locate the corresponding ':' indicator.
        # Simple keys should be limited to a single line and 1024 characters.

        # Can a simple key start at the current position? A simple key may
        # start:
        # - at the beginning of the line, not counting indentation spaces
        #       (in block context),
        # - after '{', '[', ',' (in the flow context),
        # - after '?', ':', '-' (in the block context).
        # In the block context, this flag also signifies if a block collection
        # may start at the current position.
        self.allow_simple_key = True

        # Keep track of possible simple keys. This is a dictionary. The key
        # is `flow_level`; there can be no more that one possible simple key
        # for each level. The value is a SimpleKey record:
        #   (token_number, required, index, line, column, mark)
        # A simple key may start with ALIAS, ANCHOR, TAG, SCALAR(flow),
        # '[', or '{' tokens.
        self.possible_simple_keys: Dict[Any, Any] = {}

    @property
    def reader(self) -> Any:
        try:
            return self._scanner_reader  # type: ignore
        except AttributeError:
            if hasattr(self.loader, 'typ'):
                self._scanner_reader = self.loader.reader
            else:
                self._scanner_reader = self.loader._reader
            return self._scanner_reader

    @property
    def scanner_processing_version(self) -> Any:  # prefix until un-composited
        if hasattr(self.loader, 'typ'):
            return self.loader.resolver.processing_version
        return self.loader.processing_version

    # Public methods.

    def check_token(self, *choices: Any) -> bool:
        # Check if the next token is one of the given types.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        if len(self.tokens) > 0:
            if not choices:
                return True
            for choice in choices:
                if isinstance(self.tokens[0], choice):
                    return True
        return False

    def peek_token(self) -> Any:
        # Return the next token, but do not delete if from the queue.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        if len(self.tokens) > 0:
            return self.tokens[0]

    def get_token(self) -> Any:
        # Return the next token.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        if len(self.tokens) > 0:
            self.tokens_taken += 1
            return self.tokens.pop(0)

    # Private methods.

    def need_more_tokens(self) -> bool:
        if self.done:
            return False
        if len(self.tokens) == 0:
            return True
        # The current token may be a potential simple key, so we
        # need to look further.
        self.stale_possible_simple_keys()
        if self.next_possible_simple_key() == self.tokens_taken:
            return True
        return False

    def fetch_comment(self, comment: Any) -> None:
        raise NotImplementedError

    def fetch_more_tokens(self) -> Any:
        # Eat whitespaces and comments until we reach the next token.
        comment = self.scan_to_next_token()
        if comment is not None:  # never happens for base scanner
            return self.fetch_comment(comment)
        # Remove obsolete possible simple keys.
        self.stale_possible_simple_keys()

        # Compare the current indentation and column. It may add some tokens
        # and decrease the current indentation level.
        self.unwind_indent(self.reader.column)

        # Peek the next character.
        ch = self.reader.peek()

        # Is it the end of stream?
        if ch == '\0':
            return self.fetch_stream_end()

        # Is it a directive?
        if ch == '%' and self.check_directive():
            return self.fetch_directive()

        # Is it the document start?
        if ch == '-' and self.check_document_start():
            return self.fetch_document_start()

        # Is it the document end?
        if ch == '.' and self.check_document_end():
            return self.fetch_document_end()

        # TODO: support for BOM within a stream.
        # if ch == '\uFEFF':
        #     return self.fetch_bom()    <-- issue BOMToken

        # Note: the order of the following checks is NOT significant.

        # Is it the flow sequence start indicator?
        if ch == '[':
            return self.fetch_flow_sequence_start()

        # Is it the flow mapping start indicator?
        if ch == '{':
            return self.fetch_flow_mapping_start()

        # Is it the flow sequence end indicator?
        if ch == ']':
            return self.fetch_flow_sequence_end()

        # Is it the flow mapping end indicator?
        if ch == '}':
            return self.fetch_flow_mapping_end()

        # Is it the flow entry indicator?
        if ch == ',':
            return self.fetch_flow_entry()

        # Is it the block entry indicator?
        if ch == '-' and self.check_block_entry():
            return self.fetch_block_entry()

        # Is it the key indicator?
        if ch == '?' and self.check_key():
            return self.fetch_key()

        # Is it the value indicator?
        if ch == ':' and self.check_value():
            return self.fetch_value()

        # Is it an alias?
        if ch == '*':
            return self.fetch_alias()

        # Is it an anchor?
        if ch == '&':
            return self.fetch_anchor()

        # Is it a tag?
        if ch == '!':
            return self.fetch_tag()

        # Is it a literal scalar?
        if ch == '|' and not self.flow_level:
            return self.fetch_literal()

        # Is it a folded scalar?
        if ch == '>' and not self.flow_level:
            return self.fetch_folded()

        # Is it a single quoted scalar?
        if ch == "'":
            return self.fetch_single()

        # Is it a double quoted scalar?
        if ch == '"':
            return self.fetch_double()

        # It must be a plain scalar then.
        if self.check_plain():
            return self.fetch_plain()

        # No? It's an error. Let's produce a nice error message.
        raise ScannerError(
            'while scanning for the next token',
            None,
            f'found character {ch!r} that cannot start any token',
            self.reader.get_mark(),
        )

    # Simple keys treatment.

    def next_possible_simple_key(self) -> Any:
        # Return the number of the nearest possible simple key. Actually we
        # don't need to loop through the whole dictionary. We may replace it
        # with the following code:
        #   if not self.possible_simple_keys:
        #       return None
        #   return self.possible_simple_keys[
        #           min(self.possible_simple_keys.keys())].token_number
        min_token_number = None
        for level in self.possible_simple_keys:
            key = self.possible_simple_keys[level]
            if min_token_number is None or key.token_number < min_token_number:
                min_token_number = key.token_number
        return min_token_number

    def stale_possible_simple_keys(self) -> None:
        # Remove entries that are no longer possible simple keys. According to
        # the YAML specification, simple keys
        # - should be limited to a single line,
        # - should be no longer than 1024 characters.
        # Disabling this procedure will allow simple keys of any length and
        # height (may cause problems if indentation is broken though).
        for level in list(self.possible_simple_keys):
            key = self.possible_simple_keys[level]
            if key.line != self.reader.line or self.reader.index - key.index > 1024:
                if key.required:
                    raise ScannerError(
                        'while scanning a simple key',
                        key.mark,
                        "could not find expected ':'",
                        self.reader.get_mark(),
                    )
                del self.possible_simple_keys[level]

    def save_possible_simple_key(self) -> None:
        # The next token may start a simple key. We check if it's possible
        # and save its position. This function is called for
        #   ALIAS, ANCHOR, TAG, SCALAR(flow), '[', and '{'.

        # Check if a simple key is required at the current position.
        required = not self.flow_level and self.indent == self.reader.column

        # The next token might be a simple key. Let's save it's number and
        # position.
        if self.allow_simple_key:
            self.remove_possible_simple_key()
            token_number = self.tokens_taken + len(self.tokens)
            key = SimpleKey(
                token_number,
                required,
                self.reader.index,
                self.reader.line,
                self.reader.column,
                self.reader.get_mark(),
            )
            self.possible_simple_keys[self.flow_level] = key

    def remove_possible_simple_key(self) -> None:
        # Remove the saved possible key position at the current flow level.
        if self.flow_level in self.possible_simple_keys:
            key = self.possible_simple_keys[self.flow_level]

            if key.required:
                raise ScannerError(
                    'while scanning a simple key',
                    key.mark,
                    "could not find expected ':'",
                    self.reader.get_mark(),
                )

            del self.possible_simple_keys[self.flow_level]

    # Indentation functions.

    def unwind_indent(self, column: Any) -> None:
        # In flow context, tokens should respect indentation.
        # Actually the condition should be `self.indent >= column` according to
        # the spec. But this condition will prohibit intuitively correct
        # constructions such as
        # key : {
        # }
        # ####
        # if self.flow_level and self.indent > column:
        #     raise ScannerError(None, None,
        #             "invalid intendation or unclosed '[' or '{'",
        #             self.reader.get_mark())

        # In the flow context, indentation is ignored. We make the scanner less
        # restrictive then specification requires.
        if bool(self.flow_level):
            return

        # In block context, we may need to issue the BLOCK-END tokens.
        while self.indent > column:
            mark = self.reader.get_mark()
            self.indent = self.indents.pop()
            self.tokens.append(BlockEndToken(mark, mark))

    def add_indent(self, column: int) -> bool:
        # Check if we need to increase indentation.
        if self.indent < column:
            self.indents.append(self.indent)
            self.indent = column
            return True
        return False

    # Fetchers.

    def fetch_stream_start(self) -> None:
        # We always add STREAM-START as the first token and STREAM-END as the
        # last token.
        # Read the token.
        mark = self.reader.get_mark()
        # Add STREAM-START.
        self.tokens.append(StreamStartToken(mark, mark, encoding=self.reader.encoding))

    def fetch_stream_end(self) -> None:
        # Set the current intendation to -1.
        self.unwind_indent(-1)
        # Reset simple keys.
        self.remove_possible_simple_key()
        self.allow_simple_key = False
        self.possible_simple_keys = {}
        # Read the token.
        mark = self.reader.get_mark()
        # Add STREAM-END.
        self.tokens.append(StreamEndToken(mark, mark))
        # The steam is finished.
        self.done = True

    def fetch_directive(self) -> None:
        # Set the current intendation to -1.
        self.unwind_indent(-1)

        # Reset simple keys.
        self.remove_possible_simple_key()
        self.allow_simple_key = False

        # Scan and add DIRECTIVE.
        self.tokens.append(self.scan_directive())

    def fetch_document_start(self) -> None:
        self.fetch_document_indicator(DocumentStartToken)

    def fetch_document_end(self) -> None:
        self.fetch_document_indicator(DocumentEndToken)

    def fetch_document_indicator(self, TokenClass: Any) -> None:
        # Set the current intendation to -1.
        self.unwind_indent(-1)

        # Reset simple keys. Note that there could not be a block collection
        # after '---'.
        self.remove_possible_simple_key()
        self.allow_simple_key = False

        # Add DOCUMENT-START or DOCUMENT-END.
        start_mark = self.reader.get_mark()
        self.reader.forward(3)
        end_mark = self.reader.get_mark()
        self.tokens.append(TokenClass(start_mark, end_mark))

    def fetch_flow_sequence_start(self) -> None:
        self.fetch_flow_collection_start(FlowSequenceStartToken, to_push='[')

    def fetch_flow_mapping_start(self) -> None:
        self.fetch_flow_collection_start(FlowMappingStartToken, to_push='{')

    def fetch_flow_collection_start(self, TokenClass: Any, to_push: Text) -> None:
        # '[' and '{' may start a simple key.
        self.save_possible_simple_key()
        # Increase the flow level.
        self.flow_context.append(to_push)
        # Simple keys are allowed after '[' and '{'.
        self.allow_simple_key = True
        # Add FLOW-SEQUENCE-START or FLOW-MAPPING-START.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(TokenClass(start_mark, end_mark))

    def fetch_flow_sequence_end(self) -> None:
        self.fetch_flow_collection_end(FlowSequenceEndToken)

    def fetch_flow_mapping_end(self) -> None:
        self.fetch_flow_collection_end(FlowMappingEndToken)

    def fetch_flow_collection_end(self, TokenClass: Any) -> None:
        # Reset possible simple key on the current level.
        self.remove_possible_simple_key()
        # Decrease the flow level.
        try:
            popped = self.flow_context.pop()  # NOQA
        except IndexError:
            # We must not be in a list or object.
            # Defer error handling to the parser.
            pass
        # No simple keys after ']' or '}'.
        self.allow_simple_key = False
        # Add FLOW-SEQUENCE-END or FLOW-MAPPING-END.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(TokenClass(start_mark, end_mark))

    def fetch_flow_entry(self) -> None:
        # Simple keys are allowed after ','.
        self.allow_simple_key = True
        # Reset possible simple key on the current level.
        self.remove_possible_simple_key()
        # Add FLOW-ENTRY.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(FlowEntryToken(start_mark, end_mark))

    def fetch_block_entry(self) -> None:
        # Block context needs additional checks.
        if not self.flow_level:
            # Are we allowed to start a new entry?
            if not self.allow_simple_key:
                raise ScannerError(
                    None,
                    None,
                    'sequence entries are not allowed here',
                    self.reader.get_mark(),
                )
            # We may need to add BLOCK-SEQUENCE-START.
            if self.add_indent(self.reader.column):
                mark = self.reader.get_mark()
                self.tokens.append(BlockSequenceStartToken(mark, mark))
        # It's an error for the block entry to occur in the flow context,
        # but we let the parser detect this.
        else:
            pass
        # Simple keys are allowed after '-'.
        self.allow_simple_key = True
        # Reset possible simple key on the current level.
        self.remove_possible_simple_key()

        # Add BLOCK-ENTRY.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(BlockEntryToken(start_mark, end_mark))

    def fetch_key(self) -> None:
        # Block context needs additional checks.
        if not self.flow_level:

            # Are we allowed to start a key (not nessesary a simple)?
            if not self.allow_simple_key:
                raise ScannerError(
                    None, None, 'mapping keys are not allowed here', self.reader.get_mark(),
                )

            # We may need to add BLOCK-MAPPING-START.
            if self.add_indent(self.reader.column):
                mark = self.reader.get_mark()
                self.tokens.append(BlockMappingStartToken(mark, mark))

        # Simple keys are allowed after '?' in the block context.
        self.allow_simple_key = not self.flow_level

        # Reset possible simple key on the current level.
        self.remove_possible_simple_key()

        # Add KEY.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(KeyToken(start_mark, end_mark))

    def fetch_value(self) -> None:
        # Do we determine a simple key?
        if self.flow_level in self.possible_simple_keys:
            # Add KEY.
            key = self.possible_simple_keys[self.flow_level]
            del self.possible_simple_keys[self.flow_level]
            self.tokens.insert(
                key.token_number - self.tokens_taken, KeyToken(key.mark, key.mark),
            )

            # If this key starts a new block mapping, we need to add
            # BLOCK-MAPPING-START.
            if not self.flow_level:
                if self.add_indent(key.column):
                    self.tokens.insert(
                        key.token_number - self.tokens_taken,
                        BlockMappingStartToken(key.mark, key.mark),
                    )

            # There cannot be two simple keys one after another.
            self.allow_simple_key = False

        # It must be a part of a complex key.
        else:

            # Block context needs additional checks.
            # (Do we really need them? They will be caught by the parser
            # anyway.)
            if not self.flow_level:

                # We are allowed to start a complex value if and only if
                # we can start a simple key.
                if not self.allow_simple_key:
                    raise ScannerError(
                        None,
                        None,
                        'mapping values are not allowed here',
                        self.reader.get_mark(),
                    )

            # If this value starts a new block mapping, we need to add
            # BLOCK-MAPPING-START.  It will be detected as an error later by
            # the parser.
            if not self.flow_level:
                if self.add_indent(self.reader.column):
                    mark = self.reader.get_mark()
                    self.tokens.append(BlockMappingStartToken(mark, mark))

            # Simple keys are allowed after ':' in the block context.
            self.allow_simple_key = not self.flow_level

            # Reset possible simple key on the current level.
            self.remove_possible_simple_key()

        # Add VALUE.
        start_mark = self.reader.get_mark()
        self.reader.forward()
        end_mark = self.reader.get_mark()
        self.tokens.append(ValueToken(start_mark, end_mark))

    def fetch_alias(self) -> None:
        # ALIAS could be a simple key.
        self.save_possible_simple_key()
        # No simple keys after ALIAS.
        self.allow_simple_key = False
        # Scan and add ALIAS.
        self.tokens.append(self.scan_anchor(AliasToken))

    def fetch_anchor(self) -> None:
        # ANCHOR could start a simple key.
        self.save_possible_simple_key()
        # No simple keys after ANCHOR.
        self.allow_simple_key = False
        # Scan and add ANCHOR.
        self.tokens.append(self.scan_anchor(AnchorToken))

    def fetch_tag(self) -> None:
        # TAG could start a simple key.
        self.save_possible_simple_key()
        # No simple keys after TAG.
        self.allow_simple_key = False
        # Scan and add TAG.
        self.tokens.append(self.scan_tag())

    def fetch_literal(self) -> None:
        self.fetch_block_scalar(style='|')

    def fetch_folded(self) -> None:
        self.fetch_block_scalar(style='>')

    def fetch_block_scalar(self, style: Any) -> None:
        # A simple key may follow a block scalar.
        self.allow_simple_key = True
        # Reset possible simple key on the current level.
        self.remove_possible_simple_key()
        # Scan and add SCALAR.
        self.tokens.append(self.scan_block_scalar(style))

    def fetch_single(self) -> None:
        self.fetch_flow_scalar(style="'")

    def fetch_double(self) -> None:
        self.fetch_flow_scalar(style='"')

    def fetch_flow_scalar(self, style: Any) -> None:
        # A flow scalar could be a simple key.
        self.save_possible_simple_key()
        # No simple keys after flow scalars.
        self.allow_simple_key = False
        # Scan and add SCALAR.
        self.tokens.append(self.scan_flow_scalar(style))

    def fetch_plain(self) -> None:
        # A plain scalar could be a simple key.
        self.save_possible_simple_key()
        # No simple keys after plain scalars. But note that `scan_plain` will
        # change this flag if the scan is finished at the beginning of the
        # line.
        self.allow_simple_key = False
        # Scan and add SCALAR. May change `allow_simple_key`.
        self.tokens.append(self.scan_plain())

    # Checkers.

    def check_directive(self) -> Any:
        # DIRECTIVE:        ^ '%' ...
        # The '%' indicator is already checked.
        if self.reader.column == 0:
            return True
        return None

    def check_document_start(self) -> Any:
        # DOCUMENT-START:   ^ '---' (' '|'\n')
        if self.reader.column == 0:
            if self.reader.prefix(3) == '---' and self.reader.peek(3) in _THE_END_SPACE_TAB:
                return True
        return None

    def check_document_end(self) -> Any:
        # DOCUMENT-END:     ^ '...' (' '|'\n')
        if self.reader.column == 0:
            if self.reader.prefix(3) == '...' and self.reader.peek(3) in _THE_END_SPACE_TAB:
                return True
        return None

    def check_block_entry(self) -> Any:
        # BLOCK-ENTRY:      '-' (' '|'\n')
        return self.reader.peek(1) in _THE_END_SPACE_TAB

    def check_key(self) -> Any:
        # KEY(flow context):    '?'
        if bool(self.flow_level):
            return True
        # KEY(block context):   '?' (' '|'\n')
        return self.reader.peek(1) in _THE_END_SPACE_TAB

    def check_value(self) -> Any:
        # VALUE(flow context):  ':'
        if self.scanner_processing_version == (1, 1):
            if bool(self.flow_level):
                return True
        else:
            if bool(self.flow_level):
                if self.flow_context[-1] == '[':
                    if self.reader.peek(1) not in _THE_END_SPACE_TAB:
                        return False
                elif self.tokens and isinstance(self.tokens[-1], ValueToken):
                    # mapping flow context scanning a value token
                    if self.reader.peek(1) not in _THE_END_SPACE_TAB:
                        return False
                return True
        # VALUE(block context): ':' (' '|'\n')
        return self.reader.peek(1) in _THE_END_SPACE_TAB

    def check_plain(self) -> Any:
        # A plain scalar may start with any non-space character except:
        #   '-', '?', ':', ',', '[', ']', '{', '}',
        #   '#', '&', '*', '!', '|', '>', '\'', '\"',
        #   '%', '@', '`'.
        #
        # It may also start with
        #   '-', '?', ':'
        # if it is followed by a non-space character.
        #
        # Note that we limit the last rule to the block context (except the
        # '-' character) because we want the flow context to be space
        # independent.
        srp = self.reader.peek
        ch = srp()
        if self.scanner_processing_version == (1, 1):
            return ch not in '\0 \t\r\n\x85\u2028\u2029-?:,[]{}#&*!|>\'"%@`' or (
                srp(1) not in _THE_END_SPACE_TAB
                and (ch == '-' or (not self.flow_level and ch in '?:'))
            )
        # YAML 1.2
        if ch not in '\0 \t\r\n\x85\u2028\u2029-?:,[]{}#&*!|>\'"%@`':
            # ###################                ^ ???
            return True
        ch1 = srp(1)
        if ch == '-' and ch1 not in _THE_END_SPACE_TAB:
            return True
        if ch == ':' and bool(self.flow_level) and ch1 not in _SPACE_TAB:
            return True

        return srp(1) not in _THE_END_SPACE_TAB and (
            ch == '-' or (not self.flow_level and ch in '?:')
        )

    # Scanners.

    def scan_to_next_token(self) -> Any:
        # We ignore spaces, line breaks and comments.
        # If we find a line break in the block context, we set the flag
        # `allow_simple_key` on.
        # The byte order mark is stripped if it's the first character in the
        # stream. We do not yet support BOM inside the stream as the
        # specification requires. Any such mark will be considered as a part
        # of the document.
        #
        # TODO: We need to make tab handling rules more sane. A good rule is
        #   Tabs cannot precede tokens
        #   BLOCK-SEQUENCE-START, BLOCK-MAPPING-START, BLOCK-END,
        #   KEY(block), VALUE(block), BLOCK-ENTRY
        # So the checking code is
        #   if <TAB>:
        #       self.allow_simple_keys = False
        # We also need to add the check for `allow_simple_keys == True` to
        # `unwind_indent` before issuing BLOCK-END.
        # Scanners for block, flow, and plain scalars need to be modified.
        srp = self.reader.peek
        srf = self.reader.forward
        if self.reader.index == 0 and srp() == '\uFEFF':
            srf()
        found = False
        _the_end = _THE_END
        white_space = ' \t' if self.flow_level > 0 else ' '
        while not found:
            while srp() in white_space:
                srf()
            if srp() == '#':
                while srp() not in _the_end:
                    srf()
            if self.scan_line_break():
                if not self.flow_level:
                    self.allow_simple_key = True
            else:
                found = True
        return None

    def scan_directive(self) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        start_mark = self.reader.get_mark()
        srf()
        name = self.scan_directive_name(start_mark)
        value = None
        if name == 'YAML':
            value = self.scan_yaml_directive_value(start_mark)
            end_mark = self.reader.get_mark()
        elif name == 'TAG':
            value = self.scan_tag_directive_value(start_mark)
            end_mark = self.reader.get_mark()
        else:
            end_mark = self.reader.get_mark()
            while srp() not in _THE_END:
                srf()
        self.scan_directive_ignored_line(start_mark)
        return DirectiveToken(name, value, start_mark, end_mark)

    def scan_directive_name(self, start_mark: Any) -> Any:
        # See the specification for details.
        length = 0
        srp = self.reader.peek
        ch = srp(length)
        while '0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or ch in '-_:.':
            length += 1
            ch = srp(length)
        if not length:
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f'expected alphabetic or numeric character, but found {ch!r}',
                self.reader.get_mark(),
            )
        value = self.reader.prefix(length)
        self.reader.forward(length)
        ch = srp()
        if ch not in '\0 \r\n\x85\u2028\u2029':
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f'expected alphabetic or numeric character, but found {ch!r}',
                self.reader.get_mark(),
            )
        return value

    def scan_yaml_directive_value(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        while srp() == ' ':
            srf()
        major = self.scan_yaml_directive_number(start_mark)
        if srp() != '.':
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f"expected a digit or '.', but found {srp()!r}",
                self.reader.get_mark(),
            )
        srf()
        minor = self.scan_yaml_directive_number(start_mark)
        if srp() not in '\0 \r\n\x85\u2028\u2029':
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f"expected a digit or '.', but found {srp()!r}",
                self.reader.get_mark(),
            )
        self.yaml_version = (major, minor)
        return self.yaml_version

    def scan_yaml_directive_number(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        ch = srp()
        if not ('0' <= ch <= '9'):
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f'expected a digit, but found {ch!r}',
                self.reader.get_mark(),
            )
        length = 0
        while '0' <= srp(length) <= '9':
            length += 1
        value = int(self.reader.prefix(length))
        srf(length)
        return value

    def scan_tag_directive_value(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        while srp() == ' ':
            srf()
        handle = self.scan_tag_directive_handle(start_mark)
        while srp() == ' ':
            srf()
        prefix = self.scan_tag_directive_prefix(start_mark)
        return (handle, prefix)

    def scan_tag_directive_handle(self, start_mark: Any) -> Any:
        # See the specification for details.
        value = self.scan_tag_handle('directive', start_mark)
        ch = self.reader.peek()
        if ch != ' ':
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f"expected ' ', but found {ch!r}",
                self.reader.get_mark(),
            )
        return value

    def scan_tag_directive_prefix(self, start_mark: Any) -> Any:
        # See the specification for details.
        value = self.scan_tag_uri('directive', start_mark)
        ch = self.reader.peek()
        if ch not in '\0 \r\n\x85\u2028\u2029':
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f"expected ' ', but found {ch!r}",
                self.reader.get_mark(),
            )
        return value

    def scan_directive_ignored_line(self, start_mark: Any) -> None:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        while srp() == ' ':
            srf()
        if srp() == '#':
            while srp() not in _THE_END:
                srf()
        ch = srp()
        if ch not in _THE_END:
            raise ScannerError(
                'while scanning a directive',
                start_mark,
                f'expected a comment or a line break, but found {ch!r}',
                self.reader.get_mark(),
            )
        self.scan_line_break()

    def scan_anchor(self, TokenClass: Any) -> Any:
        # The specification does not restrict characters for anchors and
        # aliases. This may lead to problems, for instance, the document:
        #   [ *alias, value ]
        # can be interpteted in two ways, as
        #   [ "value" ]
        # and
        #   [ *alias , "value" ]
        # Therefore we restrict aliases to numbers and ASCII letters.
        srp = self.reader.peek
        start_mark = self.reader.get_mark()
        indicator = srp()
        if indicator == '*':
            name = 'alias'
        else:
            name = 'anchor'
        self.reader.forward()
        length = 0
        ch = srp(length)
        # while '0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' \
        #         or ch in '-_':
        while check_anchorname_char(ch):
            length += 1
            ch = srp(length)
        if not length:
            raise ScannerError(
                f'while scanning an {name!s}',
                start_mark,
                f'expected alphabetic or numeric character, but found {ch!r}',
                self.reader.get_mark(),
            )
        value = self.reader.prefix(length)
        self.reader.forward(length)
        # ch1 = ch
        # ch = srp()   # no need to peek, ch is already set
        # assert ch1 == ch
        if ch not in '\0 \t\r\n\x85\u2028\u2029?:,[]{}%@`':
            raise ScannerError(
                f'while scanning an {name!s}',
                start_mark,
                f'expected alphabetic or numeric character, but found {ch!r}',
                self.reader.get_mark(),
            )
        end_mark = self.reader.get_mark()
        return TokenClass(value, start_mark, end_mark)

    def scan_tag(self) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        start_mark = self.reader.get_mark()
        ch = srp(1)
        short_handle = '!'
        if ch == '!':
            short_handle = '!!'
            self.reader.forward()
            srp = self.reader.peek
            ch = srp(1)

        if ch == '<':
            handle = None
            self.reader.forward(2)
            suffix = self.scan_tag_uri('tag', start_mark)
            if srp() != '>':
                raise ScannerError(
                    'while parsing a tag',
                    start_mark,
                    f"expected '>' but found {srp()!r}",
                    self.reader.get_mark(),
                )
            self.reader.forward()
        elif ch in _THE_END_SPACE_TAB:
            handle = None
            suffix = short_handle
            self.reader.forward()
        else:
            length = 1
            use_handle = False
            while ch not in '\0 \r\n\x85\u2028\u2029':
                if ch == '!':
                    use_handle = True
                    break
                length += 1
                ch = srp(length)
            handle = short_handle
            if use_handle:
                handle = self.scan_tag_handle('tag', start_mark)
            else:
                handle = short_handle
                self.reader.forward()
            suffix = self.scan_tag_uri('tag', start_mark)
        ch = srp()
        if ch not in '\0 \r\n\x85\u2028\u2029':
            raise ScannerError(
                'while scanning a tag',
                start_mark,
                f"expected ' ', but found {ch!r}",
                self.reader.get_mark(),
            )
        value = (handle, suffix)
        end_mark = self.reader.get_mark()
        return TagToken(value, start_mark, end_mark)

    def scan_block_scalar(self, style: Any, rt: Optional[bool] = False) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        if style == '>':
            folded = True
        else:
            folded = False

        chunks: List[Any] = []
        start_mark = self.reader.get_mark()

        # Scan the header.
        self.reader.forward()
        chomping, increment = self.scan_block_scalar_indicators(start_mark)
        # block scalar comment e.g. : |+  # comment text
        block_scalar_comment = self.scan_block_scalar_ignored_line(start_mark)

        # Determine the indentation level and go to the first non-empty line.
        min_indent = self.indent + 1
        if increment is None:
            # no increment and top level, min_indent could be 0
            if min_indent < 1 and (
                style not in '|>'
                or (self.scanner_processing_version == (1, 1))
                and getattr(
                    self.loader, 'top_level_block_style_scalar_no_indent_error_1_1', False,
                )
            ):
                min_indent = 1
            breaks, max_indent, end_mark = self.scan_block_scalar_indentation()
            indent = max(min_indent, max_indent)
        else:
            if min_indent < 1:
                min_indent = 1
            indent = min_indent + increment - 1
            breaks, end_mark = self.scan_block_scalar_breaks(indent)
        line_break = ""

        # Scan the inner part of the block scalar.
        while self.reader.column == indent and srp() != '\0':
            chunks.extend(breaks)
            leading_non_space = srp() not in ' \t'
            length = 0
            while srp(length) not in _THE_END:
                length += 1
            chunks.append(self.reader.prefix(length))
            self.reader.forward(length)
            line_break = self.scan_line_break()
            breaks, end_mark = self.scan_block_scalar_breaks(indent)
            if style in '|>' and min_indent == 0:
                # at the beginning of a line, if in block style see if
                # end of document/start_new_document
                if self.check_document_start() or self.check_document_end():
                    break
            if self.reader.column == indent and srp() != '\0':

                # Unfortunately, folding rules are ambiguous.
                #
                # This is the folding according to the specification:

                if rt and folded and line_break == '\n':
                    chunks.append('\a')
                if folded and line_break == '\n' and leading_non_space and srp() not in ' \t':
                    if not breaks:
                        chunks.append(' ')
                else:
                    chunks.append(line_break)

                # This is Clark Evans's interpretation (also in the spec
                # examples):
                #
                # if folded and line_break == '\n':
                #     if not breaks:
                #         if srp() not in ' \t':
                #             chunks.append(' ')
                #         else:
                #             chunks.append(line_break)
                # else:
                #     chunks.append(line_break)
            else:
                break

        # Process trailing line breaks. The 'chomping' setting determines
        # whether they are included in the value.
        trailing: List[Any] = []
        if chomping in [None, True]:
            chunks.append(line_break)
        if chomping is True:
            chunks.extend(breaks)
        elif chomping in [None, False]:
            trailing.extend(breaks)

        # We are done.
        token = ScalarToken("".join(chunks), False, start_mark, end_mark, style)
        if self.loader is not None:
            comment_handler = getattr(self.loader, 'comment_handling', False)
            if comment_handler is None:
                if block_scalar_comment is not None:
                    token.add_pre_comments([block_scalar_comment])
        if len(trailing) > 0:
            # Eat whitespaces and comments until we reach the next token.
            if self.loader is not None:
                comment_handler = getattr(self.loader, 'comment_handling', None)
                if comment_handler is not None:
                    line = end_mark.line - len(trailing)
                    for x in trailing:
                        assert x[-1] == '\n'
                        self.comments.add_blank_line(x, 0, line)  # type: ignore
                        line += 1
            comment = self.scan_to_next_token()
            while comment:
                trailing.append(' ' * comment[1].column + comment[0])
                comment = self.scan_to_next_token()
            if self.loader is not None:
                comment_handler = getattr(self.loader, 'comment_handling', False)
                if comment_handler is None:
                    # Keep track of the trailing whitespace and following comments
                    # as a comment token, if isn't all included in the actual value.
                    comment_end_mark = self.reader.get_mark()
                    comment = CommentToken("".join(trailing), end_mark, comment_end_mark)
                    token.add_post_comment(comment)
        return token

    def scan_block_scalar_indicators(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        chomping = None
        increment = None
        ch = srp()
        if ch in '+-':
            if ch == '+':
                chomping = True
            else:
                chomping = False
            self.reader.forward()
            ch = srp()
            if ch in '0123456789':
                increment = int(ch)
                if increment == 0:
                    raise ScannerError(
                        'while scanning a block scalar',
                        start_mark,
                        'expected indentation indicator in the range 1-9, ' 'but found 0',
                        self.reader.get_mark(),
                    )
                self.reader.forward()
        elif ch in '0123456789':
            increment = int(ch)
            if increment == 0:
                raise ScannerError(
                    'while scanning a block scalar',
                    start_mark,
                    'expected indentation indicator in the range 1-9, ' 'but found 0',
                    self.reader.get_mark(),
                )
            self.reader.forward()
            ch = srp()
            if ch in '+-':
                if ch == '+':
                    chomping = True
                else:
                    chomping = False
                self.reader.forward()
        ch = srp()
        if ch not in '\0 \r\n\x85\u2028\u2029':
            raise ScannerError(
                'while scanning a block scalar',
                start_mark,
                f'expected chomping or indentation indicators, but found {ch!r}',
                self.reader.get_mark(),
            )
        return chomping, increment

    def scan_block_scalar_ignored_line(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        prefix = ''
        comment = None
        while srp() == ' ':
            prefix += srp()
            srf()
        if srp() == '#':
            comment = prefix
            while srp() not in _THE_END:
                comment += srp()
                srf()
        ch = srp()
        if ch not in _THE_END:
            raise ScannerError(
                'while scanning a block scalar',
                start_mark,
                f'expected a comment or a line break, but found {ch!r}',
                self.reader.get_mark(),
            )
        self.scan_line_break()
        return comment

    def scan_block_scalar_indentation(self) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        chunks = []
        first_indent = -1
        max_indent = 0
        end_mark = self.reader.get_mark()
        while srp() in ' \r\n\x85\u2028\u2029':
            if srp() != ' ':
                if first_indent < 0:
                    first_indent = self.reader.column
                chunks.append(self.scan_line_break())
                end_mark = self.reader.get_mark()
            else:
                srf()
                if self.reader.column > max_indent:
                    max_indent = self.reader.column
        if first_indent > 0 and max_indent > first_indent:
            start_mark = self.reader.get_mark()
            raise ScannerError(
                'more indented follow up line than first in a block scalar', start_mark,
            )
        return chunks, max_indent, end_mark

    def scan_block_scalar_breaks(self, indent: int) -> Any:
        # See the specification for details.
        chunks = []
        srp = self.reader.peek
        srf = self.reader.forward
        end_mark = self.reader.get_mark()
        while self.reader.column < indent and srp() == ' ':
            srf()
        while srp() in '\r\n\x85\u2028\u2029':
            chunks.append(self.scan_line_break())
            end_mark = self.reader.get_mark()
            while self.reader.column < indent and srp() == ' ':
                srf()
        return chunks, end_mark

    def scan_flow_scalar(self, style: Any) -> Any:
        # See the specification for details.
        # Note that we loose indentation rules for quoted scalars. Quoted
        # scalars don't need to adhere indentation because " and ' clearly
        # mark the beginning and the end of them. Therefore we are less
        # restrictive then the specification requires. We only need to check
        # that document separators are not included in scalars.
        if style == '"':
            double = True
        else:
            double = False
        srp = self.reader.peek
        chunks: List[Any] = []
        start_mark = self.reader.get_mark()
        quote = srp()
        self.reader.forward()
        chunks.extend(self.scan_flow_scalar_non_spaces(double, start_mark))
        while srp() != quote:
            chunks.extend(self.scan_flow_scalar_spaces(double, start_mark))
            chunks.extend(self.scan_flow_scalar_non_spaces(double, start_mark))
        self.reader.forward()
        end_mark = self.reader.get_mark()
        return ScalarToken("".join(chunks), False, start_mark, end_mark, style)

    ESCAPE_REPLACEMENTS = {
        '0': '\0',
        'a': '\x07',
        'b': '\x08',
        't': '\x09',
        '\t': '\x09',
        'n': '\x0A',
        'v': '\x0B',
        'f': '\x0C',
        'r': '\x0D',
        'e': '\x1B',
        ' ': '\x20',
        '"': '"',
        '/': '/',  # as per http://www.json.org/
        '\\': '\\',
        'N': '\x85',
        '_': '\xA0',
        'L': '\u2028',
        'P': '\u2029',
    }

    ESCAPE_CODES = {'x': 2, 'u': 4, 'U': 8}

    def scan_flow_scalar_non_spaces(self, double: Any, start_mark: Any) -> Any:
        # See the specification for details.
        chunks: List[Any] = []
        srp = self.reader.peek
        srf = self.reader.forward
        while True:
            length = 0
            while srp(length) not in ' \n\'"\\\0\t\r\x85\u2028\u2029':
                length += 1
            if length != 0:
                chunks.append(self.reader.prefix(length))
                srf(length)
            ch = srp()
            if not double and ch == "'" and srp(1) == "'":
                chunks.append("'")
                srf(2)
            elif (double and ch == "'") or (not double and ch in '"\\'):
                chunks.append(ch)
                srf()
            elif double and ch == '\\':
                srf()
                ch = srp()
                if ch in self.ESCAPE_REPLACEMENTS:
                    chunks.append(self.ESCAPE_REPLACEMENTS[ch])
                    srf()
                elif ch in self.ESCAPE_CODES:
                    length = self.ESCAPE_CODES[ch]
                    srf()
                    for k in range(length):
                        if srp(k) not in '0123456789ABCDEFabcdef':
                            raise ScannerError(
                                'while scanning a double-quoted scalar',
                                start_mark,
                                f'expected escape sequence of {length:d} '
                                f'hexdecimal numbers, but found {srp(k)!r}',
                                self.reader.get_mark(),
                            )
                    code = int(self.reader.prefix(length), 16)
                    chunks.append(chr(code))
                    srf(length)
                elif ch in '\n\r\x85\u2028\u2029':
                    self.scan_line_break()
                    chunks.extend(self.scan_flow_scalar_breaks(double, start_mark))
                else:
                    raise ScannerError(
                        'while scanning a double-quoted scalar',
                        start_mark,
                        f'found unknown escape character {ch!r}',
                        self.reader.get_mark(),
                    )
            else:
                return chunks

    def scan_flow_scalar_spaces(self, double: Any, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        chunks = []
        length = 0
        while srp(length) in ' \t':
            length += 1
        whitespaces = self.reader.prefix(length)
        self.reader.forward(length)
        ch = srp()
        if ch == '\0':
            raise ScannerError(
                'while scanning a quoted scalar',
                start_mark,
                'found unexpected end of stream',
                self.reader.get_mark(),
            )
        elif ch in '\r\n\x85\u2028\u2029':
            line_break = self.scan_line_break()
            breaks = self.scan_flow_scalar_breaks(double, start_mark)
            if line_break != '\n':
                chunks.append(line_break)
            elif not breaks:
                chunks.append(' ')
            chunks.extend(breaks)
        else:
            chunks.append(whitespaces)
        return chunks

    def scan_flow_scalar_breaks(self, double: Any, start_mark: Any) -> Any:
        # See the specification for details.
        chunks: List[Any] = []
        srp = self.reader.peek
        srf = self.reader.forward
        while True:
            # Instead of checking indentation, we check for document
            # separators.
            prefix = self.reader.prefix(3)
            if (prefix == '---' or prefix == '...') and srp(3) in _THE_END_SPACE_TAB:
                raise ScannerError(
                    'while scanning a quoted scalar',
                    start_mark,
                    'found unexpected document separator',
                    self.reader.get_mark(),
                )
            while srp() in ' \t':
                srf()
            if srp() in '\r\n\x85\u2028\u2029':
                chunks.append(self.scan_line_break())
            else:
                return chunks

    def scan_plain(self) -> Any:
        # See the specification for details.
        # We add an additional restriction for the flow context:
        #   plain scalars in the flow context cannot contain ',', ': '  and '?'.
        # We also keep track of the `allow_simple_key` flag here.
        # Indentation rules are loosed for the flow context.
        srp = self.reader.peek
        srf = self.reader.forward
        chunks: List[Any] = []
        start_mark = self.reader.get_mark()
        end_mark = start_mark
        indent = self.indent + 1
        # We allow zero indentation for scalars, but then we need to check for
        # document separators at the beginning of the line.
        # if indent == 0:
        #     indent = 1
        spaces: List[Any] = []
        while True:
            length = 0
            if srp() == '#':
                break
            while True:
                ch = srp(length)
                if False and ch == ':' and srp(length + 1) == ',':
                    break
                elif ch == ':' and srp(length + 1) not in _THE_END_SPACE_TAB:
                    pass
                elif ch == '?' and self.scanner_processing_version != (1, 1):
                    pass
                elif (
                    ch in _THE_END_SPACE_TAB
                    or (
                        not self.flow_level
                        and ch == ':'
                        and srp(length + 1) in _THE_END_SPACE_TAB
                    )
                    or (self.flow_level and ch in ',:?[]{}')
                ):
                    break
                length += 1
            # It's not clear what we should do with ':' in the flow context.
            if (
                self.flow_level
                and ch == ':'
                and srp(length + 1) not in '\0 \t\r\n\x85\u2028\u2029,[]{}'
            ):
                srf(length)
                raise ScannerError(
                    'while scanning a plain scalar',
                    start_mark,
                    "found unexpected ':'",
                    self.reader.get_mark(),
                    'Please check '
                    'http://pyyaml.org/wiki/YAMLColonInFlowContext '
                    'for details.',
                )
            if length == 0:
                break
            self.allow_simple_key = False
            chunks.extend(spaces)
            chunks.append(self.reader.prefix(length))
            srf(length)
            end_mark = self.reader.get_mark()
            spaces = self.scan_plain_spaces(indent, start_mark)
            if (
                not spaces
                or srp() == '#'
                or (not self.flow_level and self.reader.column < indent)
            ):
                break

        token = ScalarToken("".join(chunks), True, start_mark, end_mark)
        # getattr provides True so C type loader, which cannot handle comment,
        # will not make CommentToken
        if self.loader is not None:
            comment_handler = getattr(self.loader, 'comment_handling', False)
            if comment_handler is None:
                if spaces and spaces[0] == '\n':
                    # Create a comment token to preserve the trailing line breaks.
                    comment = CommentToken("".join(spaces) + '\n', start_mark, end_mark)
                    token.add_post_comment(comment)
            elif comment_handler is not False:
                line = start_mark.line + 1
                for ch in spaces:
                    if ch == '\n':
                        self.comments.add_blank_line('\n', 0, line)  # type: ignore
                        line += 1

        return token

    def scan_plain_spaces(self, indent: Any, start_mark: Any) -> Any:
        # See the specification for details.
        # The specification is really confusing about tabs in plain scalars.
        # We just forbid them completely. Do not use tabs in YAML!
        srp = self.reader.peek
        srf = self.reader.forward
        chunks = []
        length = 0
        while srp(length) in ' ':
            length += 1
        whitespaces = self.reader.prefix(length)
        self.reader.forward(length)
        ch = srp()
        if ch in '\r\n\x85\u2028\u2029':
            line_break = self.scan_line_break()
            self.allow_simple_key = True
            prefix = self.reader.prefix(3)
            if (prefix == '---' or prefix == '...') and srp(3) in _THE_END_SPACE_TAB:
                return
            breaks = []
            while srp() in ' \r\n\x85\u2028\u2029':
                if srp() == ' ':
                    srf()
                else:
                    breaks.append(self.scan_line_break())
                    prefix = self.reader.prefix(3)
                    if (prefix == '---' or prefix == '...') and srp(3) in _THE_END_SPACE_TAB:
                        return
            if line_break != '\n':
                chunks.append(line_break)
            elif not breaks:
                chunks.append(' ')
            chunks.extend(breaks)
        elif whitespaces:
            chunks.append(whitespaces)
        return chunks

    def scan_tag_handle(self, name: Any, start_mark: Any) -> Any:
        # See the specification for details.
        # For some strange reasons, the specification does not allow '_' in
        # tag handles. I have allowed it anyway.
        srp = self.reader.peek
        ch = srp()
        if ch != '!':
            raise ScannerError(
                f'while scanning an {name!s}',
                start_mark,
                f"expected '!', but found {ch!r}",
                self.reader.get_mark(),
            )
        length = 1
        ch = srp(length)
        if ch != ' ':
            while '0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or ch in '-_':
                length += 1
                ch = srp(length)
            if ch != '!':
                self.reader.forward(length)
                raise ScannerError(
                    f'while scanning an {name!s}',
                    start_mark,
                    f"expected '!' but found {ch!r}",
                    self.reader.get_mark(),
                )
            length += 1
        value = self.reader.prefix(length)
        self.reader.forward(length)
        return value

    def scan_tag_uri(self, name: Any, start_mark: Any) -> Any:
        # See the specification for details.
        # Note: we do not check if URI is well-formed.
        srp = self.reader.peek
        chunks = []
        length = 0
        ch = srp(length)
        while (
            '0' <= ch <= '9'
            or 'A' <= ch <= 'Z'
            or 'a' <= ch <= 'z'
            or ch in "-;/?:@&=+$,_.!~*'()[]%"
            or ((self.scanner_processing_version > (1, 1)) and ch == '#')
        ):
            if ch == '%':
                chunks.append(self.reader.prefix(length))
                self.reader.forward(length)
                length = 0
                chunks.append(self.scan_uri_escapes(name, start_mark))
            else:
                length += 1
            ch = srp(length)
        if length != 0:
            chunks.append(self.reader.prefix(length))
            self.reader.forward(length)
            length = 0
        if not chunks:
            raise ScannerError(
                f'while parsing an {name!s}',
                start_mark,
                f'expected URI, but found {ch!r}',
                self.reader.get_mark(),
            )
        return "".join(chunks)

    def scan_uri_escapes(self, name: Any, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        code_bytes: List[Any] = []
        mark = self.reader.get_mark()
        while srp() == '%':
            srf()
            for k in range(2):
                if srp(k) not in '0123456789ABCDEFabcdef':
                    raise ScannerError(
                        f'while scanning an {name!s}',
                        start_mark,
                        f'expected URI escape sequence of 2 hexdecimal numbers, '
                        f'but found {srp(k)!r}',
                        self.reader.get_mark(),
                    )
            code_bytes.append(int(self.reader.prefix(2), 16))
            srf(2)
        try:
            value = bytes(code_bytes).decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ScannerError(f'while scanning an {name!s}', start_mark, str(exc), mark)
        return value

    def scan_line_break(self) -> Any:
        # Transforms:
        #   '\r\n'      :   '\n'
        #   '\r'        :   '\n'
        #   '\n'        :   '\n'
        #   '\x85'      :   '\n'
        #   '\u2028'    :   '\u2028'
        #   '\u2029     :   '\u2029'
        #   default     :   ''
        ch = self.reader.peek()
        if ch in '\r\n\x85':
            if self.reader.prefix(2) == '\r\n':
                self.reader.forward(2)
            else:
                self.reader.forward()
            return '\n'
        elif ch in '\u2028\u2029':
            self.reader.forward()
            return ch
        return ""


class RoundTripScanner(Scanner):
    def check_token(self, *choices: Any) -> bool:
        # Check if the next token is one of the given types.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        self._gather_comments()
        if len(self.tokens) > 0:
            if not choices:
                return True
            for choice in choices:
                if isinstance(self.tokens[0], choice):
                    return True
        return False

    def peek_token(self) -> Any:
        # Return the next token, but do not delete if from the queue.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        self._gather_comments()
        if len(self.tokens) > 0:
            return self.tokens[0]
        return None

    def _gather_comments(self) -> Any:
        """combine multiple comment lines and assign to next non-comment-token"""
        comments: List[Any] = []
        if not self.tokens:
            return comments
        if isinstance(self.tokens[0], CommentToken):
            comment = self.tokens.pop(0)
            self.tokens_taken += 1
            comments.append(comment)
        while self.need_more_tokens():
            self.fetch_more_tokens()
            if not self.tokens:
                return comments
            if isinstance(self.tokens[0], CommentToken):
                self.tokens_taken += 1
                comment = self.tokens.pop(0)
                # nprint('dropping2', comment)
                comments.append(comment)
        if len(comments) >= 1:
            self.tokens[0].add_pre_comments(comments)
        # pull in post comment on e.g. ':'
        if not self.done and len(self.tokens) < 2:
            self.fetch_more_tokens()

    def get_token(self) -> Any:
        # Return the next token.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        self._gather_comments()
        if len(self.tokens) > 0:
            # nprint('tk', self.tokens)
            # only add post comment to single line tokens:
            # scalar, value token. FlowXEndToken, otherwise
            # hidden streamtokens could get them (leave them and they will be
            # pre comments for the next map/seq
            if (
                len(self.tokens) > 1
                and isinstance(
                    self.tokens[0],
                    (ScalarToken, ValueToken, FlowSequenceEndToken, FlowMappingEndToken),
                )
                and isinstance(self.tokens[1], CommentToken)
                and self.tokens[0].end_mark.line == self.tokens[1].start_mark.line
            ):
                self.tokens_taken += 1
                c = self.tokens.pop(1)
                self.fetch_more_tokens()
                while len(self.tokens) > 1 and isinstance(self.tokens[1], CommentToken):
                    self.tokens_taken += 1
                    c1 = self.tokens.pop(1)
                    c.value = c.value + (' ' * c1.start_mark.column) + c1.value
                    self.fetch_more_tokens()
                self.tokens[0].add_post_comment(c)
            elif (
                len(self.tokens) > 1
                and isinstance(self.tokens[0], ScalarToken)
                and isinstance(self.tokens[1], CommentToken)
                and self.tokens[0].end_mark.line != self.tokens[1].start_mark.line
            ):
                self.tokens_taken += 1
                c = self.tokens.pop(1)
                c.value = (
                    '\n' * (c.start_mark.line - self.tokens[0].end_mark.line)
                    + (' ' * c.start_mark.column)
                    + c.value
                )
                self.tokens[0].add_post_comment(c)
                self.fetch_more_tokens()
                while len(self.tokens) > 1 and isinstance(self.tokens[1], CommentToken):
                    self.tokens_taken += 1
                    c1 = self.tokens.pop(1)
                    c.value = c.value + (' ' * c1.start_mark.column) + c1.value
                    self.fetch_more_tokens()
            self.tokens_taken += 1
            return self.tokens.pop(0)
        return None

    def fetch_comment(self, comment: Any) -> None:
        value, start_mark, end_mark = comment
        while value and value[-1] == ' ':
            # empty line within indented key context
            # no need to update end-mark, that is not used
            value = value[:-1]
        self.tokens.append(CommentToken(value, start_mark, end_mark))

    # scanner

    def scan_to_next_token(self) -> Any:
        # We ignore spaces, line breaks and comments.
        # If we find a line break in the block context, we set the flag
        # `allow_simple_key` on.
        # The byte order mark is stripped if it's the first character in the
        # stream. We do not yet support BOM inside the stream as the
        # specification requires. Any such mark will be considered as a part
        # of the document.
        #
        # TODO: We need to make tab handling rules more sane. A good rule is
        #   Tabs cannot precede tokens
        #   BLOCK-SEQUENCE-START, BLOCK-MAPPING-START, BLOCK-END,
        #   KEY(block), VALUE(block), BLOCK-ENTRY
        # So the checking code is
        #   if <TAB>:
        #       self.allow_simple_keys = False
        # We also need to add the check for `allow_simple_keys == True` to
        # `unwind_indent` before issuing BLOCK-END.
        # Scanners for block, flow, and plain scalars need to be modified.
        srp = self.reader.peek
        srf = self.reader.forward
        if self.reader.index == 0 and srp() == '\uFEFF':
            srf()
        found = False
        white_space = ' \t' if self.flow_level > 0 else ' '
        while not found:
            while srp() in white_space:
                srf()
            ch = srp()
            if ch == '#':
                start_mark = self.reader.get_mark()
                comment = ch
                srf()
                while ch not in _THE_END:
                    ch = srp()
                    if ch == '\0':  # don't gobble the end-of-stream character
                        # but add an explicit newline as "YAML processors should terminate
                        # the stream with an explicit line break
                        # https://yaml.org/spec/1.2/spec.html#id2780069
                        comment += '\n'
                        break
                    comment += ch
                    srf()
                # gather any blank lines following the comment
                ch = self.scan_line_break()
                while len(ch) > 0:
                    comment += ch
                    ch = self.scan_line_break()
                end_mark = self.reader.get_mark()
                if not self.flow_level:
                    self.allow_simple_key = True
                return comment, start_mark, end_mark
            if self.scan_line_break() != '':
                start_mark = self.reader.get_mark()
                if not self.flow_level:
                    self.allow_simple_key = True
                ch = srp()
                if ch == '\n':  # empty toplevel lines
                    start_mark = self.reader.get_mark()
                    comment = ""
                    while ch:
                        ch = self.scan_line_break(empty_line=True)
                        comment += ch
                    if srp() == '#':
                        # empty line followed by indented real comment
                        comment = comment.rsplit('\n', 1)[0] + '\n'
                    end_mark = self.reader.get_mark()
                    return comment, start_mark, end_mark
            else:
                found = True
        return None

    def scan_line_break(self, empty_line: bool = False) -> Text:
        # Transforms:
        #   '\r\n'      :   '\n'
        #   '\r'        :   '\n'
        #   '\n'        :   '\n'
        #   '\x85'      :   '\n'
        #   '\u2028'    :   '\u2028'
        #   '\u2029     :   '\u2029'
        #   default     :   ''
        ch: Text = self.reader.peek()
        if ch in '\r\n\x85':
            if self.reader.prefix(2) == '\r\n':
                self.reader.forward(2)
            else:
                self.reader.forward()
            return '\n'
        elif ch in '\u2028\u2029':
            self.reader.forward()
            return ch
        elif empty_line and ch in '\t ':
            self.reader.forward()
            return ch
        return ""

    def scan_block_scalar(self, style: Any, rt: Optional[bool] = True) -> Any:
        return Scanner.scan_block_scalar(self, style, rt=rt)

    def scan_uri_escapes(self, name: Any, start_mark: Any) -> Any:
        """
        The roundtripscanner doesn't do URI escaping
        """
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        code_bytes: List[Any] = []
        chunk = ''
        mark = self.reader.get_mark()
        while srp() == '%':
            chunk += '%'
            srf()
            for k in range(2):
                if srp(k) not in '0123456789ABCDEFabcdef':
                    raise ScannerError(
                        f'while scanning an {name!s}',
                        start_mark,
                        f'expected URI escape sequence of 2 hexdecimal numbers, '
                        f'but found {srp(k)!r}',
                        self.reader.get_mark(),
                    )
            code_bytes.append(int(self.reader.prefix(2), 16))
            chunk += self.reader.prefix(2)
            srf(2)
        try:
            _ = bytes(code_bytes).decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ScannerError(f'while scanning an {name!s}', start_mark, str(exc), mark)
        return chunk


# commenthandling 2021, differentiatiation not needed

VALUECMNT = 0
KEYCMNT = 0  # 1
# TAGCMNT = 2
# ANCHORCMNT = 3


class CommentBase:
    __slots__ = ('value', 'line', 'column', 'used', 'function', 'fline', 'ufun', 'uline')

    def __init__(self, value: Any, line: Any, column: Any) -> None:
        self.value = value
        self.line = line
        self.column = column
        self.used = ' '
        info = inspect.getframeinfo(inspect.stack()[3][0])
        self.function = info.function
        self.fline = info.lineno
        self.ufun = None
        self.uline = None

    def set_used(self, v: Any = '+') -> None:
        self.used = v
        info = inspect.getframeinfo(inspect.stack()[1][0])
        self.ufun = info.function  # type: ignore
        self.uline = info.lineno  # type: ignore

    def set_assigned(self) -> None:
        self.used = '|'

    def __str__(self) -> str:
        return f'{self.value}'

    def __repr__(self) -> str:
        return f'{self.value!r}'

    def info(self) -> str:
        xv = self.value + '"'
        name = self.name  # type: ignore
        return (
            f'{name}{self.used} {self.line:2}:{self.column:<2} "{xv:40s} '
            f'{self.function}:{self.fline} {self.ufun}:{self.uline}'
        )


class EOLComment(CommentBase):
    name = 'EOLC'

    def __init__(self, value: Any, line: Any, column: Any) -> None:
        super().__init__(value, line, column)


class FullLineComment(CommentBase):
    name = 'FULL'

    def __init__(self, value: Any, line: Any, column: Any) -> None:
        super().__init__(value, line, column)


class BlankLineComment(CommentBase):
    name = 'BLNK'

    def __init__(self, value: Any, line: Any, column: Any) -> None:
        super().__init__(value, line, column)


class ScannedComments:
    def __init__(self: Any) -> None:
        self.comments = {}  # type: ignore
        self.unused = []  # type: ignore

    def add_eol_comment(self, comment: Any, column: Any, line: Any) -> Any:
        # info = inspect.getframeinfo(inspect.stack()[1][0])
        if comment.count('\n') == 1:
            assert comment[-1] == '\n'
        else:
            assert '\n' not in comment
        self.comments[line] = retval = EOLComment(comment[:-1], line, column)
        self.unused.append(line)
        return retval

    def add_blank_line(self, comment: Any, column: Any, line: Any) -> Any:
        # info = inspect.getframeinfo(inspect.stack()[1][0])
        assert comment.count('\n') == 1 and comment[-1] == '\n'
        assert line not in self.comments
        self.comments[line] = retval = BlankLineComment(comment[:-1], line, column)
        self.unused.append(line)
        return retval

    def add_full_line_comment(self, comment: Any, column: Any, line: Any) -> Any:
        # info = inspect.getframeinfo(inspect.stack()[1][0])
        assert comment.count('\n') == 1 and comment[-1] == '\n'
        # if comment.startswith('# C12'):
        #    raise
        # this raises in line 2127 fro 330
        self.comments[line] = retval = FullLineComment(comment[:-1], line, column)
        self.unused.append(line)
        return retval

    def __getitem__(self, idx: Any) -> Any:
        return self.comments[idx]

    def __str__(self) -> Any:
        return (
            'ParsedComments:\n  '
            + '\n  '.join((f'{lineno:2} {x.info()}' for lineno, x in self.comments.items()))
            + '\n'
        )

    def last(self) -> str:
        lineno, x = list(self.comments.items())[-1]
        return f'{lineno:2} {x.info()}\n'

    def any_unprocessed(self) -> bool:
        # ToDo: might want to differentiate based on lineno
        return len(self.unused) > 0
        # for lno, comment in reversed(self.comments.items()):
        #    if comment.used == ' ':
        #        return True
        # return False

    def unprocessed(self, use: Any = False) -> Any:
        while len(self.unused) > 0:
            first = self.unused.pop(0) if use else self.unused[0]
            info = inspect.getframeinfo(inspect.stack()[1][0])
            xprintf('using', first, self.comments[first].value, info.function, info.lineno)
            yield first, self.comments[first]
            if use:
                self.comments[first].set_used()

    def assign_pre(self, token: Any) -> Any:
        token_line = token.start_mark.line
        info = inspect.getframeinfo(inspect.stack()[1][0])
        xprintf('assign_pre', token_line, self.unused, info.function, info.lineno)
        gobbled = False
        while self.unused and self.unused[0] < token_line:
            gobbled = True
            first = self.unused.pop(0)
            xprintf('assign_pre < ', first)
            self.comments[first].set_used()
            token.add_comment_pre(first)
        return gobbled

    def assign_eol(self, tokens: Any) -> Any:
        try:
            comment_line = self.unused[0]
        except IndexError:
            return
        if not isinstance(self.comments[comment_line], EOLComment):
            return
        idx = 1
        while tokens[-idx].start_mark.line > comment_line or isinstance(
            tokens[-idx], ValueToken,
        ):
            idx += 1
        xprintf('idx1', idx)
        if (
            len(tokens) > idx
            and isinstance(tokens[-idx], ScalarToken)
            and isinstance(tokens[-(idx + 1)], ScalarToken)
        ):
            return
        try:
            if isinstance(tokens[-idx], ScalarToken) and isinstance(
                tokens[-(idx + 1)], KeyToken,
            ):
                try:
                    eol_idx = self.unused.pop(0)
                    self.comments[eol_idx].set_used()
                    xprintf('>>>>>a', idx, eol_idx, KEYCMNT)
                    tokens[-idx].add_comment_eol(eol_idx, KEYCMNT)
                except IndexError:
                    raise NotImplementedError
                return
        except IndexError:
            xprintf('IndexError1')
            pass
        try:
            if isinstance(tokens[-idx], ScalarToken) and isinstance(
                tokens[-(idx + 1)], (ValueToken, BlockEntryToken),
            ):
                try:
                    eol_idx = self.unused.pop(0)
                    self.comments[eol_idx].set_used()
                    tokens[-idx].add_comment_eol(eol_idx, VALUECMNT)
                except IndexError:
                    raise NotImplementedError
                return
        except IndexError:
            xprintf('IndexError2')
            pass
        for t in tokens:
            xprintf('tt-', t)
        xprintf('not implemented EOL', type(tokens[-idx]))
        import sys

        sys.exit(0)

    def assign_post(self, token: Any) -> Any:
        token_line = token.start_mark.line
        info = inspect.getframeinfo(inspect.stack()[1][0])
        xprintf('assign_post', token_line, self.unused, info.function, info.lineno)
        gobbled = False
        while self.unused and self.unused[0] < token_line:
            gobbled = True
            first = self.unused.pop(0)
            xprintf('assign_post < ', first)
            self.comments[first].set_used()
            token.add_comment_post(first)
        return gobbled

    def str_unprocessed(self) -> Any:
        return ''.join(
            (f'  {ind:2} {x.info()}\n' for ind, x in self.comments.items() if x.used == ' '),
        )


class RoundTripScannerSC(Scanner):  # RoundTripScanner Split Comments
    def __init__(self, *arg: Any, **kw: Any) -> None:
        super().__init__(*arg, **kw)
        assert self.loader is not None
        # comments isinitialised on .need_more_tokens and persist on
        # self.loader.parsed_comments
        self.comments = None

    def get_token(self) -> Any:
        # Return the next token.
        while self.need_more_tokens():
            self.fetch_more_tokens()
        if len(self.tokens) > 0:
            if isinstance(self.tokens[0], BlockEndToken):
                self.comments.assign_post(self.tokens[0])  # type: ignore
            else:
                self.comments.assign_pre(self.tokens[0])  # type: ignore
            self.tokens_taken += 1
            return self.tokens.pop(0)

    def need_more_tokens(self) -> bool:
        if self.comments is None:
            self.loader.parsed_comments = self.comments = ScannedComments()  # type: ignore
        if self.done:
            return False
        if len(self.tokens) == 0:
            return True
        # The current token may be a potential simple key, so we
        # need to look further.
        self.stale_possible_simple_keys()
        if self.next_possible_simple_key() == self.tokens_taken:
            return True
        if len(self.tokens) < 2:
            return True
        if self.tokens[0].start_mark.line == self.tokens[-1].start_mark.line:
            return True
        if True:
            xprintf('-x--', len(self.tokens))
            for t in self.tokens:
                xprintf(t)
            # xprintf(self.comments.last())
            xprintf(self.comments.str_unprocessed())  # type: ignore
        self.comments.assign_pre(self.tokens[0])  # type: ignore
        self.comments.assign_eol(self.tokens)  # type: ignore
        return False

    def scan_to_next_token(self) -> None:
        srp = self.reader.peek
        srf = self.reader.forward
        if self.reader.index == 0 and srp() == '\uFEFF':
            srf()
        start_mark = self.reader.get_mark()
        # xprintf('current_mark', start_mark.line, start_mark.column)
        found = False
        while not found:
            while srp() == ' ':
                srf()
            ch = srp()
            if ch == '#':
                comment_start_mark = self.reader.get_mark()
                comment = ch
                srf()  # skipt the '#'
                while ch not in _THE_END:
                    ch = srp()
                    if ch == '\0':  # don't gobble the end-of-stream character
                        # but add an explicit newline as "YAML processors should terminate
                        # the stream with an explicit line break
                        # https://yaml.org/spec/1.2/spec.html#id2780069
                        comment += '\n'
                        break
                    comment += ch
                    srf()
                # we have a comment
                if start_mark.column == 0:
                    self.comments.add_full_line_comment(  # type: ignore
                        comment, comment_start_mark.column, comment_start_mark.line,
                    )
                else:
                    self.comments.add_eol_comment(  # type: ignore
                        comment, comment_start_mark.column, comment_start_mark.line,
                    )
                    comment = ""
                # gather any blank lines or full line comments following the comment as well
                self.scan_empty_or_full_line_comments()
                if not self.flow_level:
                    self.allow_simple_key = True
                return
            if bool(self.scan_line_break()):
                # start_mark = self.reader.get_mark()
                if not self.flow_level:
                    self.allow_simple_key = True
                self.scan_empty_or_full_line_comments()
                return None
                ch = srp()
                if ch == '\n':  # empty toplevel lines
                    start_mark = self.reader.get_mark()
                    comment = ""
                    while ch:
                        ch = self.scan_line_break(empty_line=True)
                        comment += ch
                    if srp() == '#':
                        # empty line followed by indented real comment
                        comment = comment.rsplit('\n', 1)[0] + '\n'
                    _ = self.reader.get_mark()  # gobble end_mark
                    return None
            else:
                found = True
        return None

    def scan_empty_or_full_line_comments(self) -> None:
        blmark = self.reader.get_mark()
        assert blmark.column == 0
        blanks = ""
        comment = None
        mark = None
        ch = self.reader.peek()
        while True:
            # nprint('ch', repr(ch), self.reader.get_mark().column)
            if ch in '\r\n\x85\u2028\u2029':
                if self.reader.prefix(2) == '\r\n':
                    self.reader.forward(2)
                else:
                    self.reader.forward()
                if comment is not None:
                    comment += '\n'
                    self.comments.add_full_line_comment(comment, mark.column, mark.line)
                    comment = None
                else:
                    blanks += '\n'
                    self.comments.add_blank_line(blanks, blmark.column, blmark.line)  # type: ignore # NOQA
                blanks = ""
                blmark = self.reader.get_mark()
                ch = self.reader.peek()
                continue
            if comment is None:
                if ch in ' \t':
                    blanks += ch
                elif ch == '#':
                    mark = self.reader.get_mark()
                    comment = '#'
                else:
                    # xprintf('breaking on', repr(ch))
                    break
            else:
                comment += ch
            self.reader.forward()
            ch = self.reader.peek()

    def scan_block_scalar_ignored_line(self, start_mark: Any) -> Any:
        # See the specification for details.
        srp = self.reader.peek
        srf = self.reader.forward
        prefix = ''
        comment = None
        while srp() == ' ':
            prefix += srp()
            srf()
        if srp() == '#':
            comment = ''
            mark = self.reader.get_mark()
            while srp() not in _THE_END:
                comment += srp()
                srf()
            comment += '\n'  # type: ignore
        ch = srp()
        if ch not in _THE_END:
            raise ScannerError(
                'while scanning a block scalar',
                start_mark,
                f'expected a comment or a line break, but found {ch!r}',
                self.reader.get_mark(),
            )
        if comment is not None:
            self.comments.add_eol_comment(comment, mark.column, mark.line)  # type: ignore
        self.scan_line_break()
        return None
