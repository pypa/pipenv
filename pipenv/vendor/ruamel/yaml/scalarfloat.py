# coding: utf-8

import sys
from pipenv.vendor.ruamel.yaml.anchor import Anchor

from typing import Text, Any, Dict, List  # NOQA

__all__ = ['ScalarFloat', 'ExponentialFloat', 'ExponentialCapsFloat']


class ScalarFloat(float):
    def __new__(cls: Any, *args: Any, **kw: Any) -> Any:
        width = kw.pop('width', None)
        prec = kw.pop('prec', None)
        m_sign = kw.pop('m_sign', None)
        m_lead0 = kw.pop('m_lead0', 0)
        exp = kw.pop('exp', None)
        e_width = kw.pop('e_width', None)
        e_sign = kw.pop('e_sign', None)
        underscore = kw.pop('underscore', None)
        anchor = kw.pop('anchor', None)
        v = float.__new__(cls, *args, **kw)
        v._width = width
        v._prec = prec
        v._m_sign = m_sign
        v._m_lead0 = m_lead0
        v._exp = exp
        v._e_width = e_width
        v._e_sign = e_sign
        v._underscore = underscore
        if anchor is not None:
            v.yaml_set_anchor(anchor, always_dump=True)
        return v

    def __iadd__(self, a: Any) -> Any:  # type: ignore
        return float(self) + a
        x = type(self)(self + a)
        x._width = self._width
        x._underscore = self._underscore[:] if self._underscore is not None else None  # NOQA
        return x

    def __ifloordiv__(self, a: Any) -> Any:  # type: ignore
        return float(self) // a
        x = type(self)(self // a)
        x._width = self._width
        x._underscore = self._underscore[:] if self._underscore is not None else None  # NOQA
        return x

    def __imul__(self, a: Any) -> Any:  # type: ignore
        return float(self) * a
        x = type(self)(self * a)
        x._width = self._width
        x._underscore = self._underscore[:] if self._underscore is not None else None  # NOQA
        x._prec = self._prec  # check for others
        return x

    def __ipow__(self, a: Any) -> Any:  # type: ignore
        return float(self) ** a
        x = type(self)(self ** a)
        x._width = self._width
        x._underscore = self._underscore[:] if self._underscore is not None else None  # NOQA
        return x

    def __isub__(self, a: Any) -> Any:  # type: ignore
        return float(self) - a
        x = type(self)(self - a)
        x._width = self._width
        x._underscore = self._underscore[:] if self._underscore is not None else None  # NOQA
        return x

    @property
    def anchor(self) -> Any:
        if not hasattr(self, Anchor.attrib):
            setattr(self, Anchor.attrib, Anchor())
        return getattr(self, Anchor.attrib)

    def yaml_anchor(self, any: bool = False) -> Any:
        if not hasattr(self, Anchor.attrib):
            return None
        if any or self.anchor.always_dump:
            return self.anchor
        return None

    def yaml_set_anchor(self, value: Any, always_dump: bool = False) -> None:
        self.anchor.value = value
        self.anchor.always_dump = always_dump

    def dump(self, out: Any = sys.stdout) -> None:
        out.write(
            f'ScalarFloat({self}| w:{self._width}, p:{self._prec}, '  # type: ignore
            f's:{self._m_sign}, lz:{self._m_lead0}, _:{self._underscore}|{self._exp}'
            f', w:{self._e_width}, s:{self._e_sign})\n',
        )


class ExponentialFloat(ScalarFloat):
    def __new__(cls, value: Any, width: Any = None, underscore: Any = None) -> Any:
        return ScalarFloat.__new__(cls, value, width=width, underscore=underscore)


class ExponentialCapsFloat(ScalarFloat):
    def __new__(cls, value: Any, width: Any = None, underscore: Any = None) -> Any:
        return ScalarFloat.__new__(cls, value, width=width, underscore=underscore)
