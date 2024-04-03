
from __future__ import annotations

"""
In round-trip mode the original tag needs to be preserved, but the tag
transformed based on the directives needs to be available as well.

A Tag that is created during loading has a handle and a suffix.
Not all objects loaded currently have a Tag, that .tag attribute can be None
A Tag that is created for dumping only (on an object loaded without a tag) has a suffix
only.
"""

if False:  # MYPY
    from typing import Any, Dict, Optional, List, Union, Optional, Iterator  # NOQA

tag_attrib = '_yaml_tag'


class Tag:
    """store original tag information for roundtripping"""

    attrib = tag_attrib

    def __init__(self, handle: Any = None, suffix: Any = None, handles: Any = None) -> None:
        self.handle = handle
        self.suffix = suffix
        self.handles = handles
        self._transform_type: Optional[bool] = None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.trval!r})'

    def __str__(self) -> str:
        return f'{self.trval}'

    def __hash__(self) -> int:
        try:
            return self._hash_id  # type: ignore
        except AttributeError:
            self._hash_id = res = hash((self.handle, self.suffix))
            return res

    def __eq__(self, other: Any) -> bool:
        # other should not be a string, but the serializer sometimes provides these
        if isinstance(other, str):
            return self.trval == other
        return bool(self.trval == other.trval)

    def startswith(self, x: str) -> bool:
        if self.trval is not None:
            return self.trval.startswith(x)
        return False

    @property
    def trval(self) -> Optional[str]:
        try:
            return self._trval
        except AttributeError:
            pass
        if self.handle is None:
            self._trval: Optional[str] = self.uri_decoded_suffix
            return self._trval
        assert self._transform_type is not None
        if not self._transform_type:
            # the non-round-trip case
            self._trval = self.handles[self.handle] + self.uri_decoded_suffix
            return self._trval
        # round-trip case
        if self.handle == '!!' and self.suffix in (
            'null',
            'bool',
            'int',
            'float',
            'binary',
            'timestamp',
            'omap',
            'pairs',
            'set',
            'str',
            'seq',
            'map',
        ):
            self._trval = self.handles[self.handle] + self.uri_decoded_suffix
        else:
            # self._trval = self.handle + self.suffix
            self._trval = self.handles[self.handle] + self.uri_decoded_suffix
        return self._trval

    value = trval

    @property
    def uri_decoded_suffix(self) -> Optional[str]:
        try:
            return self._uri_decoded_suffix
        except AttributeError:
            pass
        if self.suffix is None:
            self._uri_decoded_suffix: Optional[str] = None
            return None
        res = ''
        # don't have to check for scanner errors here
        idx = 0
        while idx < len(self.suffix):
            ch = self.suffix[idx]
            idx += 1
            if ch != '%':
                res += ch
            else:
                res += chr(int(self.suffix[idx : idx + 2], 16))
                idx += 2
        self._uri_decoded_suffix = res
        return res

    def select_transform(self, val: bool) -> None:
        """
        val: False -> non-round-trip
             True -> round-trip
        """
        assert self._transform_type is None
        self._transform_type = val

    def check_handle(self) -> bool:
        if self.handle is None:
            return False
        return self.handle not in self.handles
