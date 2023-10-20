# coding: utf-8

from typing import Any, Dict, Optional, List, Union, Optional, Iterator  # NOQA

anchor_attrib = '_yaml_anchor'


class Anchor:
    __slots__ = 'value', 'always_dump'
    attrib = anchor_attrib

    def __init__(self) -> None:
        self.value = None
        self.always_dump = False

    def __repr__(self) -> Any:
        ad = ', (always dump)' if self.always_dump else ""
        return f'Anchor({self.value!r}{ad})'
