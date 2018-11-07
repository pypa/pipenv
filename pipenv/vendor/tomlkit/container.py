from __future__ import unicode_literals

from ._compat import decode
from .exceptions import KeyAlreadyPresent
from .exceptions import NonExistentKey
from .items import AoT
from .items import Comment
from .items import Item
from .items import Key
from .items import Null
from .items import Table
from .items import Trivia
from .items import Whitespace
from .items import item as _item


class Container(dict):
    """
    A container for items within a TOMLDocument.
    """

    def __init__(self, parsed=False):  # type: (bool) -> None
        self._map = {}  # type: Dict[Key, int]
        self._body = []  # type: List[Tuple[Optional[Key], Item]]
        self._parsed = parsed

    @property
    def body(self):  # type: () -> List[Tuple[Optional[Key], Item]]
        return self._body

    @property
    def value(self):  # type: () -> Dict[Any, Any]
        d = {}
        for k, v in self._body:
            if k is None:
                continue

            k = k.key
            v = v.value

            if isinstance(v, Container):
                v = v.value

            if k in d:
                d[k].update(v)
            else:
                d[k] = v

        return d

    def parsing(self, parsing):  # type: (bool) -> None
        self._parsed = parsing

        for k, v in self._body:
            if isinstance(v, Table):
                v.value.parsing(parsing)
            elif isinstance(v, AoT):
                for t in v.body:
                    t.value.parsing(parsing)

    def add(
        self, key, item=None
    ):  # type: (Union[Key, Item, str], Optional[Item]) -> Container
        """
        Adds an item to the current Container.
        """
        if item is None:
            if not isinstance(key, (Comment, Whitespace)):
                raise ValueError(
                    "Non comment/whitespace items must have an associated key"
                )

            key, item = None, key

        return self.append(key, item)

    def append(self, key, item):  # type: (Union[Key, str], Item) -> Container
        if not isinstance(key, Key) and key is not None:
            key = Key(key)

        if not isinstance(item, Item):
            item = _item(item)

        if isinstance(item, (AoT, Table)) and item.name is None:
            item.name = key.key

        if (
            isinstance(item, Table)
            and self._body
            and not self._parsed
            and not item.trivia.indent
        ):
            item.trivia.indent = "\n"

        if isinstance(item, AoT) and self._body and not self._parsed:
            if item and "\n" not in item[0].trivia.indent:
                item[0].trivia.indent = "\n" + item[0].trivia.indent
            else:
                self.append(None, Whitespace("\n"))

        if key is not None and key in self:
            current = self._body[self._map[key]][1]
            if isinstance(item, Table):
                if not isinstance(current, (Table, AoT)):
                    raise KeyAlreadyPresent(key)

                if item.is_aot_element():
                    # New AoT element found later on
                    # Adding it to the current AoT
                    if not isinstance(current, AoT):
                        current = AoT([current, item], parsed=self._parsed)

                        self._replace(key, key, current)
                    else:
                        current.append(item)

                    return self
                elif current.is_super_table():
                    if item.is_super_table():
                        for k, v in item.value.body:
                            current.append(k, v)

                        return self
                else:
                    raise KeyAlreadyPresent(key)
            elif isinstance(item, AoT):
                if not isinstance(current, AoT):
                    raise KeyAlreadyPresent(key)

                for table in item.body:
                    current.append(table)

                return self
            else:
                raise KeyAlreadyPresent(key)

        is_table = isinstance(item, (Table, AoT))
        if key is not None and self._body and not self._parsed:
            # If there is already at least one table in the current container
            # and the given item is not a table, we need to find the last
            # item that is not a table and insert after it
            # If no such item exists, insert at the top of the table
            key_after = None
            idx = 0
            for k, v in self._body:
                if isinstance(v, Null):
                    # This happens only after deletion
                    continue

                if isinstance(v, Whitespace) and not v.is_fixed():
                    continue

                if not is_table and isinstance(v, (Table, AoT)):
                    break

                key_after = k or idx
                idx += 1

            if key_after is not None:
                if isinstance(key_after, int):
                    if key_after + 1 < len(self._body) - 1:
                        return self._insert_at(key_after + 1, key, item)
                    else:
                        previous_item = self._body[-1][1]
                        if (
                            not isinstance(previous_item, Whitespace)
                            and not is_table
                            and "\n" not in previous_item.trivia.trail
                        ):
                            previous_item.trivia.trail += "\n"
                else:
                    return self._insert_after(key_after, key, item)
            else:
                return self._insert_at(0, key, item)

        self._map[key] = len(self._body)

        self._body.append((key, item))

        if key is not None:
            super(Container, self).__setitem__(key.key, item.value)

        return self

    def remove(self, key):  # type: (Union[Key, str]) -> Container
        if not isinstance(key, Key):
            key = Key(key)

        idx = self._map.pop(key, None)
        if idx is None:
            raise NonExistentKey(key)

        old_data = self._body[idx][1]
        trivia = getattr(old_data, "trivia", None)
        if trivia and getattr(trivia, "comment", None):
            self._body[idx] = (None, Comment(Trivia(comment_ws="", comment=trivia.comment)))
        else:
            self._body[idx] = (None, Null())
            super(Container, self).__delitem__(key.key)


        return self

    def _insert_after(
        self, key, other_key, item
    ):  # type: (Union[str, Key], Union[str, Key], Union[Item, Any]) -> Container
        if key is None:
            raise ValueError("Key cannot be null in insert_after()")

        if key not in self:
            raise NonExistentKey(key)

        if not isinstance(key, Key):
            key = Key(key)

        if not isinstance(other_key, Key):
            other_key = Key(other_key)

        item = _item(item)

        idx = self._map[key]
        current_item = self._body[idx][1]
        if "\n" not in current_item.trivia.trail:
            current_item.trivia.trail += "\n"

        # Increment indices after the current index
        for k, v in self._map.items():
            if v > idx:
                self._map[k] = v + 1

        self._map[other_key] = idx + 1
        self._body.insert(idx + 1, (other_key, item))

        if key is not None:
            super(Container, self).__setitem__(other_key.key, item.value)

        return self

    def _insert_at(
        self, idx, key, item
    ):  # type: (int, Union[str, Key], Union[Item, Any]) -> Container
        if idx > len(self._body) - 1:
            raise ValueError("Unable to insert at position {}".format(idx))

        if not isinstance(key, Key):
            key = Key(key)

        item = _item(item)

        if idx > 0:
            previous_item = self._body[idx - 1][1]
            if (
                not isinstance(previous_item, Whitespace)
                and not isinstance(item, (AoT, Table))
                and "\n" not in previous_item.trivia.trail
            ):
                previous_item.trivia.trail += "\n"

        # Increment indices after the current index
        for k, v in self._map.items():
            if v >= idx:
                self._map[k] = v + 1

        self._map[key] = idx
        self._body.insert(idx, (key, item))

        if key is not None:
            super(Container, self).__setitem__(key.key, item.value)

        return self

    def item(self, key):  # type: (Union[Key, str]) -> Item
        if not isinstance(key, Key):
            key = Key(key)

        idx = self._map.get(key, None)
        if idx is None:
            raise NonExistentKey(key)

        return self._body[idx][1]

    def last_item(self):  # type: () -> Optional[Item]
        if self._body:
            return self._body[-1][1]

    def as_string(self, prefix=None):  # type: () -> str
        s = ""
        for k, v in self._body:
            if k is not None:
                if False:
                    key = k.as_string()

                    for _k, _v in v.value.body:
                        if _k is None:
                            s += v.as_string()
                        elif isinstance(_v, Table):
                            s += v.as_string(prefix=key)
                        else:
                            _key = key
                            if prefix is not None:
                                _key = prefix + "." + _key

                            s += "{}{}{}{}{}{}{}".format(
                                _v.trivia.indent,
                                _key + "." + decode(_k.as_string()),
                                _k.sep,
                                decode(_v.as_string()),
                                _v.trivia.comment_ws,
                                decode(_v.trivia.comment),
                                _v.trivia.trail,
                            )
                elif isinstance(v, Table):
                    s += self._render_table(k, v)
                elif isinstance(v, AoT):
                    s += self._render_aot(k, v)
                else:
                    s += self._render_simple_item(k, v)
            else:
                s += self._render_simple_item(k, v)

        return s

    def _render_table(
        self, key, table, prefix=None
    ):  # (Key, Table, Optional[str]) -> str
        cur = ""

        if table.display_name is not None:
            _key = table.display_name
        else:
            _key = key.as_string()

            if prefix is not None:
                _key = prefix + "." + _key

        if not table.is_super_table():
            open_, close = "[", "]"
            if table.is_aot_element():
                open_, close = "[[", "]]"

            cur += "{}{}{}{}{}{}{}{}".format(
                table.trivia.indent,
                open_,
                decode(_key),
                close,
                table.trivia.comment_ws,
                decode(table.trivia.comment),
                table.trivia.trail,
                "\n" if "\n" not in table.trivia.trail and len(table.value) > 0 else "",
            )

        for k, v in table.value.body:
            if isinstance(v, Table):
                if v.is_super_table():
                    if k.is_dotted() and not key.is_dotted():
                        # Dotted key inside table
                        cur += self._render_table(k, v)
                    else:
                        cur += self._render_table(k, v, prefix=_key)
                else:
                    cur += self._render_table(k, v, prefix=_key)
            elif isinstance(v, AoT):
                cur += self._render_aot(k, v, prefix=_key)
            else:
                cur += self._render_simple_item(
                    k, v, prefix=_key if key.is_dotted() else None
                )

        return cur

    def _render_aot(self, key, aot, prefix=None):
        _key = key.as_string()
        if prefix is not None:
            _key = prefix + "." + _key

        cur = ""
        _key = decode(_key)
        for table in aot.body:
            cur += self._render_aot_table(table, prefix=_key)

        return cur

    def _render_aot_table(self, table, prefix=None):  # (Table, Optional[str]) -> str
        cur = ""

        _key = prefix or ""

        if not table.is_super_table():
            open_, close = "[[", "]]"

            cur += "{}{}{}{}{}{}{}".format(
                table.trivia.indent,
                open_,
                decode(_key),
                close,
                table.trivia.comment_ws,
                decode(table.trivia.comment),
                table.trivia.trail,
            )

        for k, v in table.value.body:
            if isinstance(v, Table):
                if v.is_super_table():
                    if k.is_dotted():
                        # Dotted key inside table
                        cur += self._render_table(k, v)
                    else:
                        cur += self._render_table(k, v, prefix=_key)
                else:
                    cur += self._render_table(k, v, prefix=_key)
            elif isinstance(v, AoT):
                cur += self._render_aot(k, v, prefix=_key)
            else:
                cur += self._render_simple_item(k, v)

        return cur

    def _render_simple_item(self, key, item, prefix=None):
        if key is None:
            return item.as_string()

        _key = key.as_string()
        if prefix is not None:
            _key = prefix + "." + _key

        return "{}{}{}{}{}{}{}".format(
            item.trivia.indent,
            decode(_key),
            key.sep,
            decode(item.as_string()),
            item.trivia.comment_ws,
            decode(item.trivia.comment),
            item.trivia.trail,
        )

    # Dictionary methods

    def keys(self):  # type: () -> Generator[str]
        for k, _ in self._body:
            if k is None:
                continue

            yield k.key

    def values(self):  # type: () -> Generator[Item]
        for k, v in self._body:
            if k is None:
                continue

            yield v.value

    def items(self):  # type: () -> Generator[Item]
        for k, v in self.value.items():
            if k is None:
                continue

            yield k, v

    def update(self, other):  # type: (Dict) -> None
        for k, v in other.items():
            self[k] = v

    def __contains__(self, key):  # type: (Union[Key, str]) -> bool
        if not isinstance(key, Key):
            key = Key(key)

        return key in self._map

    def __getitem__(self, key):  # type: (Union[Key, str]) -> Item
        if not isinstance(key, Key):
            key = Key(key)

        idx = self._map.get(key, None)
        if idx is None:
            raise NonExistentKey(key)

        item = self._body[idx][1]

        return item.value

    def __setitem__(self, key, value):  # type: (Union[Key, str], Any) -> None
        if key is not None and key in self:
            self._replace(key, key, value)
        else:
            self.append(key, value)

    def __delitem__(self, key):  # type: (Union[Key, str]) -> None
        self.remove(key)

    def _replace(
        self, key, new_key, value
    ):  # type: (Union[Key, str], Union[Key, str], Item) -> None
        if not isinstance(key, Key):
            key = Key(key)

        if not isinstance(new_key, Key):
            new_key = Key(new_key)

        idx = self._map.get(key, None)
        if idx is None:
            raise NonExistentKey(key)

        self._replace_at(idx, new_key, value)

    def _replace_at(
        self, idx, new_key, value
    ):  # type: (int, Union[Key, str], Item) -> None
        k, v = self._body[idx]

        self._map[new_key] = self._map.pop(k)

        value = _item(value)

        # Copying trivia
        if not isinstance(value, (Whitespace, AoT)):
            value.trivia.indent = v.trivia.indent
            value.trivia.comment_ws = v.trivia.comment_ws
            value.trivia.comment = v.trivia.comment
            value.trivia.trail = v.trivia.trail

        self._body[idx] = (new_key, value)

        super(Container, self).__setitem__(new_key.key, value.value)

    def __str__(self):  # type: () -> str
        return str(self.value)

    def __eq__(self, other):  # type: (Dict) -> bool
        if not isinstance(other, dict):
            return NotImplemented

        return self.value == other

    def _getstate(self, protocol):
        return (self._parsed,)

    def __reduce__(self):
        return self.__reduce_ex__(2)

    def __reduce_ex__(self, protocol):
        return (
            self.__class__,
            self._getstate(protocol),
            (self._map, self._body, self._parsed),
        )

    def __setstate__(self, state):
        self._map = state[0]
        self._body = state[1]
        self._parsed = state[2]
