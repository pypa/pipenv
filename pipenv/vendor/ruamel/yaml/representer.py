
from __future__ import annotations

from pipenv.vendor.ruamel.yaml.error import *  # NOQA
from pipenv.vendor.ruamel.yaml.nodes import *  # NOQA
from pipenv.vendor.ruamel.yaml.compat import ordereddict
from pipenv.vendor.ruamel.yaml.compat import nprint, nprintf  # NOQA
from pipenv.vendor.ruamel.yaml.scalarstring import (
    LiteralScalarString,
    FoldedScalarString,
    SingleQuotedScalarString,
    DoubleQuotedScalarString,
    PlainScalarString,
)
from pipenv.vendor.ruamel.yaml.comments import (
    CommentedMap,
    CommentedOrderedMap,
    CommentedSeq,
    CommentedKeySeq,
    CommentedKeyMap,
    CommentedSet,
    comment_attrib,
    merge_attrib,
    TaggedScalar,
)
from pipenv.vendor.ruamel.yaml.scalarint import ScalarInt, BinaryInt, OctalInt, HexInt, HexCapsInt
from pipenv.vendor.ruamel.yaml.scalarfloat import ScalarFloat
from pipenv.vendor.ruamel.yaml.scalarbool import ScalarBoolean
from pipenv.vendor.ruamel.yaml.timestamp import TimeStamp
from pipenv.vendor.ruamel.yaml.anchor import Anchor

import collections
import datetime
import types

import copyreg
import base64

if False:  # MYPY
    from typing import Dict, List, Any, Union, Text, Optional  # NOQA

# fmt: off
__all__ = ['BaseRepresenter', 'SafeRepresenter', 'Representer',
           'RepresenterError', 'RoundTripRepresenter']
# fmt: on


class RepresenterError(YAMLError):
    pass


class BaseRepresenter:

    yaml_representers: Dict[Any, Any] = {}
    yaml_multi_representers: Dict[Any, Any] = {}

    def __init__(
        self: Any,
        default_style: Any = None,
        default_flow_style: Any = None,
        dumper: Any = None,
    ) -> None:
        self.dumper = dumper
        if self.dumper is not None:
            self.dumper._representer = self
        self.default_style = default_style
        self.default_flow_style = default_flow_style
        self.represented_objects: Dict[Any, Any] = {}
        self.object_keeper: List[Any] = []
        self.alias_key: Optional[int] = None
        self.sort_base_mapping_type_on_output = True

    @property
    def serializer(self) -> Any:
        try:
            if hasattr(self.dumper, 'typ'):
                return self.dumper.serializer
            return self.dumper._serializer
        except AttributeError:
            return self  # cyaml

    def represent(self, data: Any) -> None:
        node = self.represent_data(data)
        self.serializer.serialize(node)
        self.represented_objects = {}
        self.object_keeper = []
        self.alias_key = None

    def represent_data(self, data: Any) -> Any:
        if self.ignore_aliases(data):
            self.alias_key = None
        else:
            self.alias_key = id(data)
        if self.alias_key is not None:
            if self.alias_key in self.represented_objects:
                node = self.represented_objects[self.alias_key]
                # if node is None:
                #     raise RepresenterError(
                #          f"recursive objects are not allowed: {data!r}")
                return node
            # self.represented_objects[alias_key] = None
            self.object_keeper.append(data)
        data_types = type(data).__mro__
        if data_types[0] in self.yaml_representers:
            node = self.yaml_representers[data_types[0]](self, data)
        else:
            for data_type in data_types:
                if data_type in self.yaml_multi_representers:
                    node = self.yaml_multi_representers[data_type](self, data)
                    break
            else:
                if None in self.yaml_multi_representers:
                    node = self.yaml_multi_representers[None](self, data)
                elif None in self.yaml_representers:
                    node = self.yaml_representers[None](self, data)
                else:
                    node = ScalarNode(None, str(data))
        # if alias_key is not None:
        #     self.represented_objects[alias_key] = node
        return node

    def represent_key(self, data: Any) -> Any:
        """
        David Fraser: Extract a method to represent keys in mappings, so that
        a subclass can choose not to quote them (for example)
        used in represent_mapping
        https://bitbucket.org/davidfraser/pyyaml/commits/d81df6eb95f20cac4a79eed95ae553b5c6f77b8c
        """
        return self.represent_data(data)

    @classmethod
    def add_representer(cls, data_type: Any, representer: Any) -> None:
        if 'yaml_representers' not in cls.__dict__:
            cls.yaml_representers = cls.yaml_representers.copy()
        cls.yaml_representers[data_type] = representer

    @classmethod
    def add_multi_representer(cls, data_type: Any, representer: Any) -> None:
        if 'yaml_multi_representers' not in cls.__dict__:
            cls.yaml_multi_representers = cls.yaml_multi_representers.copy()
        cls.yaml_multi_representers[data_type] = representer

    def represent_scalar(
        self, tag: Any, value: Any, style: Any = None, anchor: Any = None,
    ) -> ScalarNode:
        if style is None:
            style = self.default_style
        comment = None
        if style and style[0] in '|>':
            comment = getattr(value, 'comment', None)
            if comment:
                comment = [None, [comment]]
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = ScalarNode(tag, value, style=style, comment=comment, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        return node

    def represent_sequence(
        self, tag: Any, sequence: Any, flow_style: Any = None,
    ) -> SequenceNode:
        value: List[Any] = []
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = SequenceNode(tag, value, flow_style=flow_style)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        for item in sequence:
            node_item = self.represent_data(item)
            if not (isinstance(node_item, ScalarNode) and not node_item.style):
                best_style = False
            value.append(node_item)
        if flow_style is None:
            if self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node

    def represent_omap(self, tag: Any, omap: Any, flow_style: Any = None) -> SequenceNode:
        value: List[Any] = []
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = SequenceNode(tag, value, flow_style=flow_style)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        for item_key in omap:
            item_val = omap[item_key]
            node_item = self.represent_data({item_key: item_val})
            # if not (isinstance(node_item, ScalarNode) \
            #    and not node_item.style):
            #     best_style = False
            value.append(node_item)
        if flow_style is None:
            if self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node

    def represent_mapping(self, tag: Any, mapping: Any, flow_style: Any = None) -> MappingNode:
        value: List[Any] = []
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = MappingNode(tag, value, flow_style=flow_style)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        if hasattr(mapping, 'items'):
            mapping = list(mapping.items())
            if self.sort_base_mapping_type_on_output:
                try:
                    mapping = sorted(mapping)
                except TypeError:
                    pass
        for item_key, item_value in mapping:
            node_key = self.represent_key(item_key)
            node_value = self.represent_data(item_value)
            if not (isinstance(node_key, ScalarNode) and not node_key.style):
                best_style = False
            if not (isinstance(node_value, ScalarNode) and not node_value.style):
                best_style = False
            value.append((node_key, node_value))
        if flow_style is None:
            if self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node

    def ignore_aliases(self, data: Any) -> bool:
        return False


class SafeRepresenter(BaseRepresenter):
    def ignore_aliases(self, data: Any) -> bool:
        # https://docs.python.org/3/reference/expressions.html#parenthesized-forms :
        # "i.e. two occurrences of the empty tuple may or may not yield the same object"
        # so "data is ()" should not be used
        if data is None or (isinstance(data, tuple) and data == ()):
            return True
        if isinstance(data, (bytes, str, bool, int, float)):
            return True
        return False

    def represent_none(self, data: Any) -> ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:null', 'null')

    def represent_str(self, data: Any) -> Any:
        return self.represent_scalar('tag:yaml.org,2002:str', data)

    def represent_binary(self, data: Any) -> ScalarNode:
        if hasattr(base64, 'encodebytes'):
            data = base64.encodebytes(data).decode('ascii')
        else:
            # check py2 only?
            data = base64.encodestring(data).decode('ascii')  # type: ignore
        return self.represent_scalar('tag:yaml.org,2002:binary', data, style='|')

    def represent_bool(self, data: Any, anchor: Optional[Any] = None) -> ScalarNode:
        try:
            value = self.dumper.boolean_representation[bool(data)]
        except AttributeError:
            if data:
                value = 'true'
            else:
                value = 'false'
        return self.represent_scalar('tag:yaml.org,2002:bool', value, anchor=anchor)

    def represent_int(self, data: Any) -> ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:int', str(data))

    inf_value = 1e300
    while repr(inf_value) != repr(inf_value * inf_value):
        inf_value *= inf_value

    def represent_float(self, data: Any) -> ScalarNode:
        if data != data or (data == 0.0 and data == 1.0):
            value = '.nan'
        elif data == self.inf_value:
            value = '.inf'
        elif data == -self.inf_value:
            value = '-.inf'
        else:
            value = repr(data).lower()
            if getattr(self.serializer, 'use_version', None) == (1, 1):
                if '.' not in value and 'e' in value:
                    # Note that in some cases `repr(data)` represents a float number
                    # without the decimal parts.  For instance:
                    #   >>> repr(1e17)
                    #   '1e17'
                    # Unfortunately, this is not a valid float representation according
                    # to the definition of the `!!float` tag in YAML 1.1.  We fix
                    # this by adding '.0' before the 'e' symbol.
                    value = value.replace('e', '.0e', 1)
        return self.represent_scalar('tag:yaml.org,2002:float', value)

    def represent_list(self, data: Any) -> SequenceNode:
        # pairs = (len(data) > 0 and isinstance(data, list))
        # if pairs:
        #     for item in data:
        #         if not isinstance(item, tuple) or len(item) != 2:
        #             pairs = False
        #             break
        # if not pairs:
        return self.represent_sequence('tag:yaml.org,2002:seq', data)

    # value = []
    # for item_key, item_value in data:
    #     value.append(self.represent_mapping('tag:yaml.org,2002:map',
    #         [(item_key, item_value)]))
    # return SequenceNode('tag:yaml.org,2002:pairs', value)

    def represent_dict(self, data: Any) -> MappingNode:
        return self.represent_mapping('tag:yaml.org,2002:map', data)

    def represent_ordereddict(self, data: Any) -> SequenceNode:
        return self.represent_omap('tag:yaml.org,2002:omap', data)

    def represent_set(self, data: Any) -> MappingNode:
        value: Dict[Any, None] = {}
        for key in data:
            value[key] = None
        return self.represent_mapping('tag:yaml.org,2002:set', value)

    def represent_date(self, data: Any) -> ScalarNode:
        value = data.isoformat()
        return self.represent_scalar('tag:yaml.org,2002:timestamp', value)

    def represent_datetime(self, data: Any) -> ScalarNode:
        value = data.isoformat(' ')
        return self.represent_scalar('tag:yaml.org,2002:timestamp', value)

    def represent_yaml_object(
        self, tag: Any, data: Any, cls: Any, flow_style: Any = None,
    ) -> MappingNode:
        if hasattr(data, '__getstate__'):
            state = data.__getstate__()
        else:
            state = data.__dict__.copy()
        return self.represent_mapping(tag, state, flow_style=flow_style)

    def represent_undefined(self, data: Any) -> None:
        raise RepresenterError(f'cannot represent an object: {data!s}')


SafeRepresenter.add_representer(type(None), SafeRepresenter.represent_none)

SafeRepresenter.add_representer(str, SafeRepresenter.represent_str)

SafeRepresenter.add_representer(bytes, SafeRepresenter.represent_binary)

SafeRepresenter.add_representer(bool, SafeRepresenter.represent_bool)

SafeRepresenter.add_representer(int, SafeRepresenter.represent_int)

SafeRepresenter.add_representer(float, SafeRepresenter.represent_float)

SafeRepresenter.add_representer(list, SafeRepresenter.represent_list)

SafeRepresenter.add_representer(tuple, SafeRepresenter.represent_list)

SafeRepresenter.add_representer(dict, SafeRepresenter.represent_dict)

SafeRepresenter.add_representer(set, SafeRepresenter.represent_set)

SafeRepresenter.add_representer(ordereddict, SafeRepresenter.represent_ordereddict)

SafeRepresenter.add_representer(
    collections.OrderedDict, SafeRepresenter.represent_ordereddict,
)

SafeRepresenter.add_representer(datetime.date, SafeRepresenter.represent_date)

SafeRepresenter.add_representer(datetime.datetime, SafeRepresenter.represent_datetime)

SafeRepresenter.add_representer(None, SafeRepresenter.represent_undefined)


class Representer(SafeRepresenter):
    def represent_complex(self, data: Any) -> Any:
        if data.imag == 0.0:
            data = repr(data.real)
        elif data.real == 0.0:
            data = f'{data.imag!r}j'
        elif data.imag > 0:
            data = f'{data.real!r}+{data.imag!r}j'
        else:
            data = f'{data.real!r}{data.imag!r}j'
        return self.represent_scalar('tag:yaml.org,2002:python/complex', data)

    def represent_tuple(self, data: Any) -> SequenceNode:
        return self.represent_sequence('tag:yaml.org,2002:python/tuple', data)

    def represent_name(self, data: Any) -> ScalarNode:
        try:
            name = f'{data.__module__!s}.{data.__qualname__!s}'
        except AttributeError:
            # ToDo: check if this can be reached in Py3
            name = f'{data.__module__!s}.{data.__name__!s}'
        return self.represent_scalar('tag:yaml.org,2002:python/name:' + name, "")

    def represent_module(self, data: Any) -> ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:python/module:' + data.__name__, "")

    def represent_object(self, data: Any) -> Union[SequenceNode, MappingNode]:
        # We use __reduce__ API to save the data. data.__reduce__ returns
        # a tuple of length 2-5:
        #   (function, args, state, listitems, dictitems)

        # For reconstructing, we calls function(*args), then set its state,
        # listitems, and dictitems if they are not None.

        # A special case is when function.__name__ == '__newobj__'. In this
        # case we create the object with args[0].__new__(*args).

        # Another special case is when __reduce__ returns a string - we don't
        # support it.

        # We produce a !!python/object, !!python/object/new or
        # !!python/object/apply node.

        cls = type(data)
        if cls in copyreg.dispatch_table:
            reduce: Any = copyreg.dispatch_table[cls](data)
        elif hasattr(data, '__reduce_ex__'):
            reduce = data.__reduce_ex__(2)
        elif hasattr(data, '__reduce__'):
            reduce = data.__reduce__()
        else:
            raise RepresenterError(f'cannot represent object: {data!r}')
        reduce = (list(reduce) + [None] * 5)[:5]
        function, args, state, listitems, dictitems = reduce
        args = list(args)
        if state is None:
            state = {}
        if listitems is not None:
            listitems = list(listitems)
        if dictitems is not None:
            dictitems = dict(dictitems)
        if function.__name__ == '__newobj__':
            function = args[0]
            args = args[1:]
            tag = 'tag:yaml.org,2002:python/object/new:'
            newobj = True
        else:
            tag = 'tag:yaml.org,2002:python/object/apply:'
            newobj = False
        try:
            function_name = f'{function.__module__!s}.{function.__qualname__!s}'
        except AttributeError:
            # ToDo: check if this can be reached in Py3
            function_name = f'{function.__module__!s}.{function.__name__!s}'
        if not args and not listitems and not dictitems and isinstance(state, dict) and newobj:
            return self.represent_mapping(
                'tag:yaml.org,2002:python/object:' + function_name, state,
            )
        if not listitems and not dictitems and isinstance(state, dict) and not state:
            return self.represent_sequence(tag + function_name, args)
        value = {}
        if args:
            value['args'] = args
        if state or not isinstance(state, dict):
            value['state'] = state
        if listitems:
            value['listitems'] = listitems
        if dictitems:
            value['dictitems'] = dictitems
        return self.represent_mapping(tag + function_name, value)


Representer.add_representer(complex, Representer.represent_complex)

Representer.add_representer(tuple, Representer.represent_tuple)

Representer.add_representer(type, Representer.represent_name)

Representer.add_representer(types.FunctionType, Representer.represent_name)

Representer.add_representer(types.BuiltinFunctionType, Representer.represent_name)

Representer.add_representer(types.ModuleType, Representer.represent_module)

Representer.add_multi_representer(object, Representer.represent_object)

Representer.add_multi_representer(type, Representer.represent_name)


class RoundTripRepresenter(SafeRepresenter):
    # need to add type here and write out the .comment
    # in serializer and emitter

    def __init__(
        self, default_style: Any = None, default_flow_style: Any = None, dumper: Any = None,
    ) -> None:
        if not hasattr(dumper, 'typ') and default_flow_style is None:
            default_flow_style = False
        SafeRepresenter.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=dumper,
        )

    def ignore_aliases(self, data: Any) -> bool:
        try:
            if data.anchor is not None and data.anchor.value is not None:
                return False
        except AttributeError:
            pass
        return SafeRepresenter.ignore_aliases(self, data)

    def represent_none(self, data: Any) -> ScalarNode:
        if len(self.represented_objects) == 0 and not self.serializer.use_explicit_start:
            # this will be open ended (although it is not yet)
            return self.represent_scalar('tag:yaml.org,2002:null', 'null')
        return self.represent_scalar('tag:yaml.org,2002:null', "")

    def represent_literal_scalarstring(self, data: Any) -> ScalarNode:
        tag = None
        style = '|'
        anchor = data.yaml_anchor(any=True)
        tag = 'tag:yaml.org,2002:str'
        return self.represent_scalar(tag, data, style=style, anchor=anchor)

    represent_preserved_scalarstring = represent_literal_scalarstring

    def represent_folded_scalarstring(self, data: Any) -> ScalarNode:
        tag = None
        style = '>'
        anchor = data.yaml_anchor(any=True)
        for fold_pos in reversed(getattr(data, 'fold_pos', [])):
            if (
                data[fold_pos] == ' '
                and (fold_pos > 0 and not data[fold_pos - 1].isspace())
                and (fold_pos < len(data) and not data[fold_pos + 1].isspace())
            ):
                data = data[:fold_pos] + '\a' + data[fold_pos:]
        tag = 'tag:yaml.org,2002:str'
        return self.represent_scalar(tag, data, style=style, anchor=anchor)

    def represent_single_quoted_scalarstring(self, data: Any) -> ScalarNode:
        tag = None
        style = "'"
        anchor = data.yaml_anchor(any=True)
        tag = 'tag:yaml.org,2002:str'
        return self.represent_scalar(tag, data, style=style, anchor=anchor)

    def represent_double_quoted_scalarstring(self, data: Any) -> ScalarNode:
        tag = None
        style = '"'
        anchor = data.yaml_anchor(any=True)
        tag = 'tag:yaml.org,2002:str'
        return self.represent_scalar(tag, data, style=style, anchor=anchor)

    def represent_plain_scalarstring(self, data: Any) -> ScalarNode:
        tag = None
        style = ''
        anchor = data.yaml_anchor(any=True)
        tag = 'tag:yaml.org,2002:str'
        return self.represent_scalar(tag, data, style=style, anchor=anchor)

    def insert_underscore(
        self, prefix: Any, s: Any, underscore: Any, anchor: Any = None,
    ) -> ScalarNode:
        if underscore is None:
            return self.represent_scalar('tag:yaml.org,2002:int', prefix + s, anchor=anchor)
        if underscore[0]:
            sl = list(s)
            pos = len(s) - underscore[0]
            while pos > 0:
                sl.insert(pos, '_')
                pos -= underscore[0]
            s = "".join(sl)
        if underscore[1]:
            s = '_' + s
        if underscore[2]:
            s += '_'
        return self.represent_scalar('tag:yaml.org,2002:int', prefix + s, anchor=anchor)

    def represent_scalar_int(self, data: Any) -> ScalarNode:
        if data._width is not None:
            s = f'{data:0{data._width}d}'
        else:
            s = format(data, 'd')
        anchor = data.yaml_anchor(any=True)
        return self.insert_underscore("", s, data._underscore, anchor=anchor)

    def represent_binary_int(self, data: Any) -> ScalarNode:
        if data._width is not None:
            # cannot use '{:#0{}b}', that strips the zeros
            s = f'{data:0{data._width}b}'
        else:
            s = format(data, 'b')
        anchor = data.yaml_anchor(any=True)
        return self.insert_underscore('0b', s, data._underscore, anchor=anchor)

    def represent_octal_int(self, data: Any) -> ScalarNode:
        if data._width is not None:
            # cannot use '{:#0{}o}', that strips the zeros
            s = f'{data:0{data._width}o}'
        else:
            s = format(data, 'o')
        anchor = data.yaml_anchor(any=True)
        prefix = '0o'
        if getattr(self.serializer, 'use_version', None) == (1, 1):
            prefix = '0'
        return self.insert_underscore(prefix, s, data._underscore, anchor=anchor)

    def represent_hex_int(self, data: Any) -> ScalarNode:
        if data._width is not None:
            # cannot use '{:#0{}x}', that strips the zeros
            s = f'{data:0{data._width}x}'
        else:
            s = format(data, 'x')
        anchor = data.yaml_anchor(any=True)
        return self.insert_underscore('0x', s, data._underscore, anchor=anchor)

    def represent_hex_caps_int(self, data: Any) -> ScalarNode:
        if data._width is not None:
            # cannot use '{:#0{}X}', that strips the zeros
            s = f'{data:0{data._width}X}'
        else:
            s = format(data, 'X')
        anchor = data.yaml_anchor(any=True)
        return self.insert_underscore('0x', s, data._underscore, anchor=anchor)

    def represent_scalar_float(self, data: Any) -> ScalarNode:
        """ this is way more complicated """
        value = None
        anchor = data.yaml_anchor(any=True)
        if data != data or (data == 0.0 and data == 1.0):
            value = '.nan'
        elif data == self.inf_value:
            value = '.inf'
        elif data == -self.inf_value:
            value = '-.inf'
        if value:
            return self.represent_scalar('tag:yaml.org,2002:float', value, anchor=anchor)
        if data._exp is None and data._prec > 0 and data._prec == data._width - 1:
            # no exponent, but trailing dot
            value = f'{data._m_sign if data._m_sign else ""}{abs(int(data)):d}.'
        elif data._exp is None:
            # no exponent, "normal" dot
            prec = data._prec
            ms = data._m_sign if data._m_sign else ""
            if prec < 0:
                value = f'{ms}{abs(int(data)):0{data._width - len(ms)}d}'
            else:
                # -1 for the dot
                value = f'{ms}{abs(data):0{data._width - len(ms)}.{data._width - prec - 1}f}'
                if prec == 0 or (prec == 1 and ms != ""):
                    value = value.replace('0.', '.')
            while len(value) < data._width:
                value += '0'
        else:
            # exponent
            (
                m,
                es,
            ) = f'{data:{data._width}.{data._width + (1 if data._m_sign else 0)}e}'.split('e')
            w = data._width if data._prec > 0 else (data._width + 1)
            if data < 0:
                w += 1
            m = m[:w]
            e = int(es)
            m1, m2 = m.split('.')  # always second?
            while len(m1) + len(m2) < data._width - (1 if data._prec >= 0 else 0):
                m2 += '0'
            if data._m_sign and data > 0:
                m1 = '+' + m1
            esgn = '+' if data._e_sign else ""
            if data._prec < 0:  # mantissa without dot
                if m2 != '0':
                    e -= len(m2)
                else:
                    m2 = ""
                while (len(m1) + len(m2) - (1 if data._m_sign else 0)) < data._width:
                    m2 += '0'
                    e -= 1
                value = m1 + m2 + data._exp + f'{e:{esgn}0{data._e_width}d}'
            elif data._prec == 0:  # mantissa with trailing dot
                e -= len(m2)
                value = m1 + m2 + '.' + data._exp + f'{e:{esgn}0{data._e_width}d}'
            else:
                if data._m_lead0 > 0:
                    m2 = '0' * (data._m_lead0 - 1) + m1 + m2
                    m1 = '0'
                    m2 = m2[: -data._m_lead0]  # these should be zeros
                    e += data._m_lead0
                while len(m1) < data._prec:
                    m1 += m2[0]
                    m2 = m2[1:]
                    e -= 1
                value = m1 + '.' + m2 + data._exp + f'{e:{esgn}0{data._e_width}d}'

        if value is None:
            value = repr(data).lower()
        return self.represent_scalar('tag:yaml.org,2002:float', value, anchor=anchor)

    def represent_sequence(
        self, tag: Any, sequence: Any, flow_style: Any = None,
    ) -> SequenceNode:
        value: List[Any] = []
        # if the flow_style is None, the flow style tacked on to the object
        # explicitly will be taken. If that is None as well the default flow
        # style rules
        try:
            flow_style = sequence.fa.flow_style(flow_style)
        except AttributeError:
            flow_style = flow_style
        try:
            anchor = sequence.yaml_anchor()
        except AttributeError:
            anchor = None
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = SequenceNode(tag, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        try:
            comment = getattr(sequence, comment_attrib)
            node.comment = comment.comment
            # reset any comment already printed information
            if node.comment and node.comment[1]:
                for ct in node.comment[1]:
                    ct.reset()
            item_comments = comment.items
            for v in item_comments.values():
                if v and v[1]:
                    for ct in v[1]:
                        ct.reset()
            item_comments = comment.items
            if node.comment is None:
                node.comment = comment.comment
            else:
                # as we are potentially going to extend this, make a new list
                node.comment = comment.comment[:]
            try:
                node.comment.append(comment.end)
            except AttributeError:
                pass
        except AttributeError:
            item_comments = {}
        for idx, item in enumerate(sequence):
            node_item = self.represent_data(item)
            self.merge_comments(node_item, item_comments.get(idx))
            if not (isinstance(node_item, ScalarNode) and not node_item.style):
                best_style = False
            value.append(node_item)
        if flow_style is None:
            if len(sequence) != 0 and self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node

    def merge_comments(self, node: Any, comments: Any) -> Any:
        if comments is None:
            assert hasattr(node, 'comment')
            return node
        if getattr(node, 'comment', None) is not None:
            for idx, val in enumerate(comments):
                if idx >= len(node.comment):
                    continue
                nc = node.comment[idx]
                if nc is not None:
                    assert val is None or val == nc
                    comments[idx] = nc
        node.comment = comments
        return node

    def represent_key(self, data: Any) -> Any:
        if isinstance(data, CommentedKeySeq):
            self.alias_key = None
            return self.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
        if isinstance(data, CommentedKeyMap):
            self.alias_key = None
            return self.represent_mapping('tag:yaml.org,2002:map', data, flow_style=True)
        return SafeRepresenter.represent_key(self, data)

    def represent_mapping(self, tag: Any, mapping: Any, flow_style: Any = None) -> MappingNode:
        value: List[Any] = []
        try:
            flow_style = mapping.fa.flow_style(flow_style)
        except AttributeError:
            flow_style = flow_style
        try:
            anchor = mapping.yaml_anchor()
        except AttributeError:
            anchor = None
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = MappingNode(tag, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        # no sorting! !!
        try:
            comment = getattr(mapping, comment_attrib)
            if node.comment is None:
                node.comment = comment.comment
            else:
                # as we are potentially going to extend this, make a new list
                node.comment = comment.comment[:]
            if node.comment and node.comment[1]:
                for ct in node.comment[1]:
                    ct.reset()
            item_comments = comment.items
            if self.dumper.comment_handling is None:
                for v in item_comments.values():
                    if v and v[1]:
                        for ct in v[1]:
                            ct.reset()
                try:
                    node.comment.append(comment.end)
                except AttributeError:
                    pass
            else:
                # NEWCMNT
                pass
        except AttributeError:
            item_comments = {}
        merge_list = [m[1] for m in getattr(mapping, merge_attrib, [])]
        try:
            merge_pos = getattr(mapping, merge_attrib, [[0]])[0][0]
        except IndexError:
            merge_pos = 0
        item_count = 0
        if bool(merge_list):
            items = mapping.non_merged_items()
        else:
            items = mapping.items()
        for item_key, item_value in items:
            item_count += 1
            node_key = self.represent_key(item_key)
            node_value = self.represent_data(item_value)
            item_comment = item_comments.get(item_key)
            if item_comment:
                # assert getattr(node_key, 'comment', None) is None
                # issue 351 did throw this because the comment from the list item was
                # moved to the dict
                node_key.comment = item_comment[:2]
                nvc = getattr(node_value, 'comment', None)
                if nvc is not None:  # end comment already there
                    nvc[0] = item_comment[2]
                    nvc[1] = item_comment[3]
                else:
                    node_value.comment = item_comment[2:]
            if not (isinstance(node_key, ScalarNode) and not node_key.style):
                best_style = False
            if not (isinstance(node_value, ScalarNode) and not node_value.style):
                best_style = False
            value.append((node_key, node_value))
        if flow_style is None:
            if ((item_count != 0) or bool(merge_list)) and self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        if bool(merge_list):
            # because of the call to represent_data here, the anchors
            # are marked as being used and thereby created
            if len(merge_list) == 1:
                arg = self.represent_data(merge_list[0])
            else:
                arg = self.represent_data(merge_list)
                arg.flow_style = True
            value.insert(
                merge_pos, (ScalarNode(Tag(suffix='tag:yaml.org,2002:merge'), '<<'), arg),
            )
        return node

    def represent_omap(self, tag: Any, omap: Any, flow_style: Any = None) -> SequenceNode:
        value: List[Any] = []
        try:
            flow_style = omap.fa.flow_style(flow_style)
        except AttributeError:
            flow_style = flow_style
        try:
            anchor = omap.yaml_anchor()
        except AttributeError:
            anchor = None
        if isinstance(tag, str):
            tag = Tag(suffix=tag)
        node = SequenceNode(tag, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        try:
            comment = getattr(omap, comment_attrib)
            if node.comment is None:
                node.comment = comment.comment
            else:
                # as we are potentially going to extend this, make a new list
                node.comment = comment.comment[:]
            if node.comment and node.comment[1]:
                for ct in node.comment[1]:
                    ct.reset()
            item_comments = comment.items
            for v in item_comments.values():
                if v and v[1]:
                    for ct in v[1]:
                        ct.reset()
            try:
                node.comment.append(comment.end)
            except AttributeError:
                pass
        except AttributeError:
            item_comments = {}
        for item_key in omap:
            item_val = omap[item_key]
            node_item = self.represent_data({item_key: item_val})
            # node_item.flow_style = False
            # node item has two scalars in value: node_key and node_value
            item_comment = item_comments.get(item_key)
            if item_comment:
                if item_comment[1]:
                    node_item.comment = [None, item_comment[1]]
                assert getattr(node_item.value[0][0], 'comment', None) is None
                node_item.value[0][0].comment = [item_comment[0], None]
                nvc = getattr(node_item.value[0][1], 'comment', None)
                if nvc is not None:  # end comment already there
                    nvc[0] = item_comment[2]
                    nvc[1] = item_comment[3]
                else:
                    node_item.value[0][1].comment = item_comment[2:]
            # if not (isinstance(node_item, ScalarNode) \
            #    and not node_item.style):
            #     best_style = False
            value.append(node_item)
        if flow_style is None:
            if self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node

    def represent_set(self, setting: Any) -> MappingNode:
        flow_style = False
        tag = Tag(suffix='tag:yaml.org,2002:set')
        # return self.represent_mapping(tag, value)
        value: List[Any] = []
        flow_style = setting.fa.flow_style(flow_style)
        try:
            anchor = setting.yaml_anchor()
        except AttributeError:
            anchor = None
        node = MappingNode(tag, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        best_style = True
        # no sorting! !!
        try:
            comment = getattr(setting, comment_attrib)
            if node.comment is None:
                node.comment = comment.comment
            else:
                # as we are potentially going to extend this, make a new list
                node.comment = comment.comment[:]
            if node.comment and node.comment[1]:
                for ct in node.comment[1]:
                    ct.reset()
            item_comments = comment.items
            for v in item_comments.values():
                if v and v[1]:
                    for ct in v[1]:
                        ct.reset()
            try:
                node.comment.append(comment.end)
            except AttributeError:
                pass
        except AttributeError:
            item_comments = {}
        for item_key in setting.odict:
            node_key = self.represent_key(item_key)
            node_value = self.represent_data(None)
            item_comment = item_comments.get(item_key)
            if item_comment:
                assert getattr(node_key, 'comment', None) is None
                node_key.comment = item_comment[:2]
            node_key.style = '?'
            node_value.style = '-' if flow_style else '?'
            if not (isinstance(node_key, ScalarNode) and not node_key.style):
                best_style = False
            if not (isinstance(node_value, ScalarNode) and not node_value.style):
                best_style = False
            value.append((node_key, node_value))
        best_style = best_style
        return node

    def represent_dict(self, data: Any) -> MappingNode:
        """write out tag if saved on loading"""
        try:
            _ = data.tag
        except AttributeError:
            tag = Tag(suffix='tag:yaml.org,2002:map')
        else:
            if data.tag.trval:
                if data.tag.startswith('!!'):
                    tag = Tag(suffix='tag:yaml.org,2002:' + data.tag.trval[2:])
                else:
                    tag = data.tag
            else:
                tag = Tag(suffix='tag:yaml.org,2002:map')
        return self.represent_mapping(tag, data)

    def represent_list(self, data: Any) -> SequenceNode:
        try:
            _ = data.tag
        except AttributeError:
            tag = Tag(suffix='tag:yaml.org,2002:seq')
        else:
            if data.tag.trval:
                if data.tag.startswith('!!'):
                    tag = Tag(suffix='tag:yaml.org,2002:' + data.tag.trval[2:])
                else:
                    tag = data.tag
            else:
                tag = Tag(suffix='tag:yaml.org,2002:seq')
        return self.represent_sequence(tag, data)

    def represent_datetime(self, data: Any) -> ScalarNode:
        inter = 'T' if data._yaml['t'] else ' '
        _yaml = data._yaml
        if False and _yaml['delta']:
            data += _yaml['delta']
            value = data.isoformat(inter)
        else:
            value = data.isoformat(inter).strip()
        if False and _yaml['tz']:
            value += _yaml['tz']
        if data.tzinfo and str(data.tzinfo):
            if value[-6] in '+-':
                value = value[:-6] + str(data.tzinfo)
        return self.represent_scalar('tag:yaml.org,2002:timestamp', value)

    def represent_tagged_scalar(self, data: Any) -> ScalarNode:
        try:
            if data.tag.handle == '!!':
                tag = f'{data.tag.handle} {data.tag.suffix}'
            else:
                tag = data.tag
        except AttributeError:
            tag = None
        try:
            anchor = data.yaml_anchor()
        except AttributeError:
            anchor = None
        return self.represent_scalar(tag, data.value, style=data.style, anchor=anchor)

    def represent_scalar_bool(self, data: Any) -> ScalarNode:
        try:
            anchor = data.yaml_anchor()
        except AttributeError:
            anchor = None
        return SafeRepresenter.represent_bool(self, data, anchor=anchor)

    def represent_yaml_object(
        self, tag: Any, data: Any, cls: Any, flow_style: Optional[Any] = None,
    ) -> MappingNode:
        if hasattr(data, '__getstate__'):
            state = data.__getstate__()
        else:
            state = data.__dict__.copy()
        anchor = state.pop(Anchor.attrib, None)
        res = self.represent_mapping(tag, state, flow_style=flow_style)
        if anchor is not None:
            res.anchor = anchor
        return res


RoundTripRepresenter.add_representer(type(None), RoundTripRepresenter.represent_none)

RoundTripRepresenter.add_representer(
    LiteralScalarString, RoundTripRepresenter.represent_literal_scalarstring,
)

RoundTripRepresenter.add_representer(
    FoldedScalarString, RoundTripRepresenter.represent_folded_scalarstring,
)

RoundTripRepresenter.add_representer(
    SingleQuotedScalarString, RoundTripRepresenter.represent_single_quoted_scalarstring,
)

RoundTripRepresenter.add_representer(
    DoubleQuotedScalarString, RoundTripRepresenter.represent_double_quoted_scalarstring,
)

RoundTripRepresenter.add_representer(
    PlainScalarString, RoundTripRepresenter.represent_plain_scalarstring,
)

# RoundTripRepresenter.add_representer(tuple, Representer.represent_tuple)

RoundTripRepresenter.add_representer(ScalarInt, RoundTripRepresenter.represent_scalar_int)

RoundTripRepresenter.add_representer(BinaryInt, RoundTripRepresenter.represent_binary_int)

RoundTripRepresenter.add_representer(OctalInt, RoundTripRepresenter.represent_octal_int)

RoundTripRepresenter.add_representer(HexInt, RoundTripRepresenter.represent_hex_int)

RoundTripRepresenter.add_representer(HexCapsInt, RoundTripRepresenter.represent_hex_caps_int)

RoundTripRepresenter.add_representer(ScalarFloat, RoundTripRepresenter.represent_scalar_float)

RoundTripRepresenter.add_representer(ScalarBoolean, RoundTripRepresenter.represent_scalar_bool)

RoundTripRepresenter.add_representer(CommentedSeq, RoundTripRepresenter.represent_list)

RoundTripRepresenter.add_representer(CommentedMap, RoundTripRepresenter.represent_dict)

RoundTripRepresenter.add_representer(
    CommentedOrderedMap, RoundTripRepresenter.represent_ordereddict,
)

RoundTripRepresenter.add_representer(
    collections.OrderedDict, RoundTripRepresenter.represent_ordereddict,
)

RoundTripRepresenter.add_representer(CommentedSet, RoundTripRepresenter.represent_set)

RoundTripRepresenter.add_representer(
    TaggedScalar, RoundTripRepresenter.represent_tagged_scalar,
)

RoundTripRepresenter.add_representer(TimeStamp, RoundTripRepresenter.represent_datetime)
