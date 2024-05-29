
from __future__ import annotations

from pipenv.vendor.ruamel.yaml.compat import nprintf  # NOQA

if False:  # MYPY
    from typing import Text, Any, Dict, Optional, List  # NOQA
from .error import StreamMark  # NOQA

SHOW_LINES = True


class Token:
    __slots__ = 'start_mark', 'end_mark', '_comment'

    def __init__(self, start_mark: StreamMark, end_mark: StreamMark) -> None:
        self.start_mark = start_mark
        self.end_mark = end_mark

    def __repr__(self) -> Any:
        # attributes = [key for key in self.__slots__ if not key.endswith('_mark') and
        #               hasattr('self', key)]
        attributes = [key for key in self.__slots__ if not key.endswith('_mark')]
        attributes.sort()
        # arguments = ', '.join(
        #  [f'{key!s}={getattr(self, key)!r})' for key in attributes]
        # )
        arguments = [f'{key!s}={getattr(self, key)!r}' for key in attributes]
        if SHOW_LINES:
            try:
                arguments.append('line: ' + str(self.start_mark.line))
            except:  # NOQA
                pass
        try:
            arguments.append('comment: ' + str(self._comment))
        except:  # NOQA
            pass
        return f'{self.__class__.__name__}({", ".join(arguments)})'

    @property
    def column(self) -> int:
        return self.start_mark.column

    @column.setter
    def column(self, pos: Any) -> None:
        self.start_mark.column = pos

    # old style ( <= 0.17) is a TWO element list with first being the EOL
    # comment concatenated with following FLC/BLNK; and second being a list of FLC/BLNK
    # preceding the token
    # new style ( >= 0.17 ) is a THREE element list with the first being a list of
    # preceding FLC/BLNK, the second EOL and the third following FLC/BLNK
    # note that new style has differing order, and does not consist of CommentToken(s)
    # but of CommentInfo instances
    # any non-assigned values in new style are None, but first and last can be empty list
    # new style routines add one comment at a time

    # going to be deprecated in favour of add_comment_eol/post
    def add_post_comment(self, comment: Any) -> None:
        if not hasattr(self, '_comment'):
            self._comment = [None, None]
        else:
            assert len(self._comment) in [2, 5]  # make sure it is version 0
        # if isinstance(comment, CommentToken):
        #    if comment.value.startswith('# C09'):
        #        raise
        self._comment[0] = comment

    # going to be deprecated in favour of add_comment_pre
    def add_pre_comments(self, comments: Any) -> None:
        if not hasattr(self, '_comment'):
            self._comment = [None, None]
        else:
            assert len(self._comment) == 2  # make sure it is version 0
        assert self._comment[1] is None
        self._comment[1] = comments
        return

    # new style
    def add_comment_pre(self, comment: Any) -> None:
        if not hasattr(self, '_comment'):
            self._comment = [[], None, None]  # type: ignore
        else:
            assert len(self._comment) == 3
            if self._comment[0] is None:
                self._comment[0] = []  # type: ignore
        self._comment[0].append(comment)  # type: ignore

    def add_comment_eol(self, comment: Any, comment_type: Any) -> None:
        if not hasattr(self, '_comment'):
            self._comment = [None, None, None]
        else:
            assert len(self._comment) == 3
            assert self._comment[1] is None
        if self.comment[1] is None:
            self._comment[1] = []  # type: ignore
        self._comment[1].extend([None] * (comment_type + 1 - len(self.comment[1])))  # type: ignore # NOQA
        # nprintf('commy', self.comment, comment_type)
        self._comment[1][comment_type] = comment  # type: ignore

    def add_comment_post(self, comment: Any) -> None:
        if not hasattr(self, '_comment'):
            self._comment = [None, None, []]  # type: ignore
        else:
            assert len(self._comment) == 3
            if self._comment[2] is None:
                self._comment[2] = []  # type: ignore
        self._comment[2].append(comment)  # type: ignore

    # def get_comment(self) -> Any:
    #     return getattr(self, '_comment', None)

    @property
    def comment(self) -> Any:
        return getattr(self, '_comment', None)

    def move_old_comment(self, target: Any, empty: bool = False) -> Any:
        """move a comment from this token to target (normally next token)
        used to combine e.g. comments before a BlockEntryToken to the
        ScalarToken that follows it
        empty is a special for empty values -> comment after key
        """
        c = self.comment
        if c is None:
            return
        # don't push beyond last element
        if isinstance(target, (StreamEndToken, DocumentStartToken)):
            return
        delattr(self, '_comment')
        tc = target.comment
        if not tc:  # target comment, just insert
            # special for empty value in key: value issue 25
            if empty:
                c = [c[0], c[1], None, None, c[0]]
            target._comment = c
            # nprint('mco2:', self, target, target.comment, empty)
            return self
        if c[0] and tc[0] or c[1] and tc[1]:
            raise NotImplementedError(f'overlap in comment {c!r} {tc!r}')
        if c[0]:
            tc[0] = c[0]
        if c[1]:
            tc[1] = c[1]
        return self

    def split_old_comment(self) -> Any:
        """ split the post part of a comment, and return it
        as comment to be added. Delete second part if [None, None]
         abc:  # this goes to sequence
           # this goes to first element
           - first element
        """
        comment = self.comment
        if comment is None or comment[0] is None:
            return None  # nothing to do
        ret_val = [comment[0], None]
        if comment[1] is None:
            delattr(self, '_comment')
        return ret_val

    def move_new_comment(self, target: Any, empty: bool = False) -> Any:
        """move a comment from this token to target (normally next token)
        used to combine e.g. comments before a BlockEntryToken to the
        ScalarToken that follows it
        empty is a special for empty values -> comment after key
        """
        c = self.comment
        if c is None:
            return
        # don't push beyond last element
        if isinstance(target, (StreamEndToken, DocumentStartToken)):
            return
        delattr(self, '_comment')
        tc = target.comment
        if not tc:  # target comment, just insert
            # special for empty value in key: value issue 25
            if empty:
                c = [c[0], c[1], c[2]]
            target._comment = c
            # nprint('mco2:', self, target, target.comment, empty)
            return self
        # if self and target have both pre, eol or post comments, something seems wrong
        for idx in range(3):
            if c[idx] is not None and tc[idx] is not None:
                raise NotImplementedError(f'overlap in comment {c!r} {tc!r}')
        # move the comment parts
        for idx in range(3):
            if c[idx]:
                tc[idx] = c[idx]
        return self


# class BOMToken(Token):
#     id = '<byte order mark>'


class DirectiveToken(Token):
    __slots__ = 'name', 'value'
    id = '<directive>'

    def __init__(self, name: Any, value: Any, start_mark: Any, end_mark: Any) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.name = name
        self.value = value


class DocumentStartToken(Token):
    __slots__ = ()
    id = '<document start>'


class DocumentEndToken(Token):
    __slots__ = ()
    id = '<document end>'


class StreamStartToken(Token):
    __slots__ = ('encoding',)
    id = '<stream start>'

    def __init__(
        self, start_mark: Any = None, end_mark: Any = None, encoding: Any = None,
    ) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.encoding = encoding


class StreamEndToken(Token):
    __slots__ = ()
    id = '<stream end>'


class BlockSequenceStartToken(Token):
    __slots__ = ()
    id = '<block sequence start>'


class BlockMappingStartToken(Token):
    __slots__ = ()
    id = '<block mapping start>'


class BlockEndToken(Token):
    __slots__ = ()
    id = '<block end>'


class FlowSequenceStartToken(Token):
    __slots__ = ()
    id = '['


class FlowMappingStartToken(Token):
    __slots__ = ()
    id = '{'


class FlowSequenceEndToken(Token):
    __slots__ = ()
    id = ']'


class FlowMappingEndToken(Token):
    __slots__ = ()
    id = '}'


class KeyToken(Token):
    __slots__ = ()
    id = '?'

#   def x__repr__(self):
#       return f'KeyToken({self.start_mark.buffer[self.start_mark.index:].split(None, 1)[0]})'


class ValueToken(Token):
    __slots__ = ()
    id = ':'


class BlockEntryToken(Token):
    __slots__ = ()
    id = '-'


class FlowEntryToken(Token):
    __slots__ = ()
    id = ','


class AliasToken(Token):
    __slots__ = ('value',)
    id = '<alias>'

    def __init__(self, value: Any, start_mark: Any, end_mark: Any) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.value = value


class AnchorToken(Token):
    __slots__ = ('value',)
    id = '<anchor>'

    def __init__(self, value: Any, start_mark: Any, end_mark: Any) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.value = value


class TagToken(Token):
    __slots__ = ('value',)
    id = '<tag>'

    def __init__(self, value: Any, start_mark: Any, end_mark: Any) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.value = value


class ScalarToken(Token):
    __slots__ = 'value', 'plain', 'style'
    id = '<scalar>'

    def __init__(
        self, value: Any, plain: Any, start_mark: Any, end_mark: Any, style: Any = None,
    ) -> None:
        Token.__init__(self, start_mark, end_mark)
        self.value = value
        self.plain = plain
        self.style = style


class CommentToken(Token):
    __slots__ = '_value', '_column', 'pre_done'
    id = '<comment>'

    def __init__(
        self, value: Any, start_mark: Any = None, end_mark: Any = None, column: Any = None,
    ) -> None:
        if start_mark is None:
            assert column is not None
            self._column = column
        Token.__init__(self, start_mark, None)  # type: ignore
        self._value = value

    @property
    def value(self) -> str:
        if isinstance(self._value, str):
            return self._value
        return "".join(self._value)

    @value.setter
    def value(self, val: Any) -> None:
        self._value = val

    def reset(self) -> None:
        if hasattr(self, 'pre_done'):
            delattr(self, 'pre_done')

    def __repr__(self) -> Any:
        v = f'{self.value!r}'
        if SHOW_LINES:
            try:
                v += ', line: ' + str(self.start_mark.line)
            except:  # NOQA
                pass
            try:
                v += ', col: ' + str(self.start_mark.column)
            except:  # NOQA
                pass
        return f'CommentToken({v})'

    def __eq__(self, other: Any) -> bool:
        if self.start_mark != other.start_mark:
            return False
        if self.end_mark != other.end_mark:
            return False
        if self.value != other.value:
            return False
        return True

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)
