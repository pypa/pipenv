
from __future__ import annotations

import sys
import os
import warnings
import glob
from importlib import import_module


import pipenv.vendor.ruamel.yaml as ruamel
from pipenv.vendor.ruamel.yaml.error import UnsafeLoaderWarning, YAMLError  # NOQA

from pipenv.vendor.ruamel.yaml.tokens import *  # NOQA
from pipenv.vendor.ruamel.yaml.events import *  # NOQA
from pipenv.vendor.ruamel.yaml.nodes import *  # NOQA

from pipenv.vendor.ruamel.yaml.loader import BaseLoader, SafeLoader, Loader, RoundTripLoader  # NOQA
from pipenv.vendor.ruamel.yaml.dumper import BaseDumper, SafeDumper, Dumper, RoundTripDumper  # NOQA
from pipenv.vendor.ruamel.yaml.compat import StringIO, BytesIO, with_metaclass, nprint, nprintf  # NOQA
from pipenv.vendor.ruamel.yaml.resolver import VersionedResolver, Resolver  # NOQA
from pipenv.vendor.ruamel.yaml.representer import (
    BaseRepresenter,
    SafeRepresenter,
    Representer,
    RoundTripRepresenter,
)
from pipenv.vendor.ruamel.yaml.constructor import (
    BaseConstructor,
    SafeConstructor,
    Constructor,
    RoundTripConstructor,
)
from pipenv.vendor.ruamel.yaml.loader import Loader as UnsafeLoader  # NOQA
from pipenv.vendor.ruamel.yaml.comments import CommentedMap, CommentedSeq, C_PRE
from pipenv.vendor.ruamel.yaml.docinfo import DocInfo, version, Version

if False:  # MYPY
    from typing import List, Set, Dict, Tuple, Union, Any, Callable, Optional, Text, Type  # NOQA
    from pipenv.vendor.ruamel.yaml.compat import StreamType, StreamTextType, VersionType  # NOQA
    from types import TracebackType
    from pathlib import Path

try:
    from _ruamel_yaml import CParser, CEmitter  # type: ignore
except:  # NOQA
    CParser = CEmitter = None

# import io


# YAML is an acronym, i.e. spoken: rhymes with "camel". And thus a
# subset of abbreviations, which should be all caps according to PEP8


class YAML:
    def __init__(
        self: Any,
        *,
        typ: Optional[Union[List[Text], Text]] = None,
        pure: Any = False,
        output: Any = None,
        plug_ins: Any = None,
    ) -> None:  # input=None,
        """
        typ: 'rt'/None -> RoundTripLoader/RoundTripDumper,  (default)
             'safe'    -> SafeLoader/SafeDumper,
             'unsafe'  -> normal/unsafe Loader/Dumper (pending deprecation)
             'full'    -> full Dumper only, including python built-ins that are
                          potentially unsafe to load
             'base'    -> baseloader
        pure: if True only use Python modules
        input/output: needed to work as context manager
        plug_ins: a list of plug-in files
        """

        self.typ = ['rt'] if typ is None else (typ if isinstance(typ, list) else [typ])
        self.pure = pure

        # self._input = input
        self._output = output
        self._context_manager: Any = None

        self.plug_ins: List[Any] = []
        for pu in ([] if plug_ins is None else plug_ins) + self.official_plug_ins():
            file_name = pu.replace(os.sep, '.')
            self.plug_ins.append(import_module(file_name))
        self.Resolver: Any = ruamel.resolver.VersionedResolver
        self.allow_unicode = True
        self.Reader: Any = None
        self.Representer: Any = None
        self.Constructor: Any = None
        self.Scanner: Any = None
        self.Serializer: Any = None
        self.default_flow_style: Any = None
        self.comment_handling = None
        typ_found = 1
        setup_rt = False
        if 'rt' in self.typ:
            setup_rt = True
        elif 'safe' in self.typ:
            self.Emitter = (
                ruamel.emitter.Emitter if pure or CEmitter is None else CEmitter
            )
            self.Representer = ruamel.representer.SafeRepresenter
            self.Parser = ruamel.parser.Parser if pure or CParser is None else CParser
            self.Composer = ruamel.composer.Composer
            self.Constructor = ruamel.constructor.SafeConstructor
        elif 'base' in self.typ:
            self.Emitter = ruamel.emitter.Emitter
            self.Representer = ruamel.representer.BaseRepresenter
            self.Parser = ruamel.parser.Parser if pure or CParser is None else CParser
            self.Composer = ruamel.composer.Composer
            self.Constructor = ruamel.constructor.BaseConstructor
        elif 'unsafe' in self.typ:
            warnings.warn(
                "\nyou should no longer specify 'unsafe'.\nFor **dumping only** use yaml=YAML(typ='full')\n",  # NOQA
                PendingDeprecationWarning,
                stacklevel=2,
            )
            self.Emitter = (
                ruamel.emitter.Emitter if pure or CEmitter is None else CEmitter
            )
            self.Representer = ruamel.representer.Representer
            self.Parser = ruamel.parser.Parser if pure or CParser is None else CParser
            self.Composer = ruamel.composer.Composer
            self.Constructor = ruamel.constructor.Constructor
        elif 'full' in self.typ:
            self.Emitter = (
                ruamel.emitter.Emitter if pure or CEmitter is None else CEmitter
            )
            self.Representer = ruamel.representer.Representer
            self.Parser = ruamel.parser.Parser if pure or CParser is None else CParser
            # self.Composer = ruamel.composer.Composer
            # self.Constructor = ruamel.constructor.Constructor
        elif 'rtsc' in self.typ:
            self.default_flow_style = False
            # no optimized rt-dumper yet
            self.Emitter = ruamel.emitter.RoundTripEmitter
            self.Serializer = ruamel.serializer.Serializer
            self.Representer = ruamel.representer.RoundTripRepresenter
            self.Scanner = ruamel.scanner.RoundTripScannerSC
            # no optimized rt-parser yet
            self.Parser = ruamel.parser.RoundTripParserSC
            self.Composer = ruamel.composer.Composer
            self.Constructor = ruamel.constructor.RoundTripConstructor
            self.comment_handling = C_PRE
        else:
            setup_rt = True
            typ_found = 0
        if setup_rt:
            self.default_flow_style = False
            # no optimized rt-dumper yet
            self.Emitter = ruamel.emitter.RoundTripEmitter
            self.Serializer = ruamel.serializer.Serializer
            self.Representer = ruamel.representer.RoundTripRepresenter
            self.Scanner = ruamel.scanner.RoundTripScanner
            # no optimized rt-parser yet
            self.Parser = ruamel.parser.RoundTripParser
            self.Composer = ruamel.composer.Composer
            self.Constructor = ruamel.constructor.RoundTripConstructor
        del setup_rt
        self.stream = None
        self.canonical = None
        self.old_indent = None
        self.width: Union[int, None] = None
        self.line_break = None

        self.map_indent: Union[int, None] = None
        self.sequence_indent: Union[int, None] = None
        self.sequence_dash_offset: int = 0
        self.compact_seq_seq = None
        self.compact_seq_map = None
        self.sort_base_mapping_type_on_output = None  # default: sort

        self.top_level_colon_align = None
        self.prefix_colon = None
        self._version: Optional[Any] = None
        self.preserve_quotes: Optional[bool] = None
        self.allow_duplicate_keys = False  # duplicate keys in map, set
        self.encoding = 'utf-8'
        self.explicit_start: Union[bool, None] = None
        self.explicit_end: Union[bool, None] = None
        self._tags = None
        self.doc_infos: List[DocInfo] = []
        self.default_style = None
        self.top_level_block_style_scalar_no_indent_error_1_1 = False
        # directives end indicator with single scalar document
        self.scalar_after_indicator: Optional[bool] = None
        # [a, b: 1, c: {d: 2}]  vs. [a, {b: 1}, {c: {d: 2}}]
        self.brace_single_entry_mapping_in_flow_sequence = False
        for module in self.plug_ins:
            if getattr(module, 'typ', None) in self.typ:
                typ_found += 1
                module.init_typ(self)
                break
        if typ_found == 0:
            raise NotImplementedError(
                f'typ "{self.typ}" not recognised (need to install plug-in?)',
            )

    @property
    def reader(self) -> Any:
        try:
            return self._reader  # type: ignore
        except AttributeError:
            self._reader = self.Reader(None, loader=self)
            return self._reader

    @property
    def scanner(self) -> Any:
        try:
            return self._scanner  # type: ignore
        except AttributeError:
            self._scanner = self.Scanner(loader=self)
            return self._scanner

    @property
    def parser(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            if self.Parser is not CParser:
                setattr(self, attr, self.Parser(loader=self))
            else:
                if getattr(self, '_stream', None) is None:
                    # wait for the stream
                    return None
                else:
                    # if not hasattr(self._stream, 'read') and hasattr(self._stream, 'open'):
                    #     # pathlib.Path() instance
                    #     setattr(self, attr, CParser(self._stream))
                    # else:
                    setattr(self, attr, CParser(self._stream))
                    # self._parser = self._composer = self
                    # nprint('scanner', self.loader.scanner)

        return getattr(self, attr)

    @property
    def composer(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            setattr(self, attr, self.Composer(loader=self))
        return getattr(self, attr)

    @property
    def constructor(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            if self.Constructor is None:
                if 'full' in self.typ:
                    raise YAMLError(
                        "\nyou can only use yaml=YAML(typ='full') for dumping\n",  # NOQA
                    )
            cnst = self.Constructor(preserve_quotes=self.preserve_quotes, loader=self)  # type: ignore # NOQA
            cnst.allow_duplicate_keys = self.allow_duplicate_keys
            setattr(self, attr, cnst)
        return getattr(self, attr)

    @property
    def resolver(self) -> Any:
        try:
            rslvr = self._resolver  # type: ignore
        except AttributeError:
            rslvr = None
        if rslvr is None or rslvr._loader_version != self.version:
            rslvr = self._resolver = self.Resolver(version=self.version, loader=self)
        return rslvr

    @property
    def emitter(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            if self.Emitter is not CEmitter:
                _emitter = self.Emitter(
                    None,
                    canonical=self.canonical,
                    indent=self.old_indent,
                    width=self.width,
                    allow_unicode=self.allow_unicode,
                    line_break=self.line_break,
                    prefix_colon=self.prefix_colon,
                    brace_single_entry_mapping_in_flow_sequence=self.brace_single_entry_mapping_in_flow_sequence,  # NOQA
                    dumper=self,
                )
                setattr(self, attr, _emitter)
                if self.map_indent is not None:
                    _emitter.best_map_indent = self.map_indent
                if self.sequence_indent is not None:
                    _emitter.best_sequence_indent = self.sequence_indent
                if self.sequence_dash_offset is not None:
                    _emitter.sequence_dash_offset = self.sequence_dash_offset
                    # _emitter.block_seq_indent = self.sequence_dash_offset
                if self.compact_seq_seq is not None:
                    _emitter.compact_seq_seq = self.compact_seq_seq
                if self.compact_seq_map is not None:
                    _emitter.compact_seq_map = self.compact_seq_map
            else:
                if getattr(self, '_stream', None) is None:
                    # wait for the stream
                    return None
                return None
        return getattr(self, attr)

    @property
    def serializer(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            setattr(
                self,
                attr,
                self.Serializer(
                    encoding=self.encoding,
                    explicit_start=self.explicit_start,
                    explicit_end=self.explicit_end,
                    version=self.version,
                    tags=self.tags,
                    dumper=self,
                ),
            )
        return getattr(self, attr)

    @property
    def representer(self) -> Any:
        attr = '_' + sys._getframe().f_code.co_name
        if not hasattr(self, attr):
            repres = self.Representer(
                default_style=self.default_style,
                default_flow_style=self.default_flow_style,
                dumper=self,
            )
            if self.sort_base_mapping_type_on_output is not None:
                repres.sort_base_mapping_type_on_output = self.sort_base_mapping_type_on_output
            setattr(self, attr, repres)
        return getattr(self, attr)

    def scan(self, stream: StreamTextType) -> Any:
        """
        Scan a YAML stream and produce scanning tokens.
        """
        if not hasattr(stream, 'read') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('rb') as fp:
                return self.scan(fp)
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        _, parser = self.get_constructor_parser(stream)
        try:
            while self.scanner.check_token():
                yield self.scanner.get_token()
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    def parse(self, stream: StreamTextType) -> Any:
        """
        Parse a YAML stream and produce parsing events.
        """
        if not hasattr(stream, 'read') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('rb') as fp:
                return self.parse(fp)
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        _, parser = self.get_constructor_parser(stream)
        try:
            while parser.check_event():
                yield parser.get_event()
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    def compose(self, stream: Union[Path, StreamTextType]) -> Any:
        """
        Parse the first YAML document in a stream
        and produce the corresponding representation tree.
        """
        if not hasattr(stream, 'read') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('rb') as fp:
                return self.compose(fp)
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        constructor, parser = self.get_constructor_parser(stream)
        try:
            return constructor.composer.get_single_node()
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    def compose_all(self, stream: Union[Path, StreamTextType]) -> Any:
        """
        Parse all YAML documents in a stream
        and produce corresponding representation trees.
        """
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        constructor, parser = self.get_constructor_parser(stream)
        try:
            while constructor.composer.check_node():
                yield constructor.composer.get_node()
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    # separate output resolver?

    # def load(self, stream=None):
    #     if self._context_manager:
    #        if not self._input:
    #             raise TypeError("Missing input stream while dumping from context manager")
    #         for data in self._context_manager.load():
    #             yield data
    #         return
    #     if stream is None:
    #         raise TypeError("Need a stream argument when not loading from context manager")
    #     return self.load_one(stream)

    def load(self, stream: Union[Path, StreamTextType]) -> Any:
        """
        at this point you either have the non-pure Parser (which has its own reader and
        scanner) or you have the pure Parser.
        If the pure Parser is set, then set the Reader and Scanner, if not already set.
        If either the Scanner or Reader are set, you cannot use the non-pure Parser,
            so reset it to the pure parser and set the Reader resp. Scanner if necessary
        """
        if not hasattr(stream, 'read') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('rb') as fp:
                return self.load(fp)
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        constructor, parser = self.get_constructor_parser(stream)
        try:
            return constructor.get_single_data()
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    def load_all(self, stream: Union[Path, StreamTextType]) -> Any:  # *, skip=None):
        if not hasattr(stream, 'read') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('r') as fp:
                for d in self.load_all(fp):
                    yield d
                return
        # if skip is None:
        #     skip = []
        # elif isinstance(skip, int):
        #     skip = [skip]
        self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        self.tags = {}
        constructor, parser = self.get_constructor_parser(stream)
        try:
            while constructor.check_data():
                yield constructor.get_data()
                self.doc_infos.append(DocInfo(requested_version=version(self.version)))
        finally:
            parser.dispose()
            for comp in ('reader', 'scanner'):
                try:
                    getattr(getattr(self, '_' + comp), f'reset_{comp}')()
                except AttributeError:
                    pass

    def get_constructor_parser(self, stream: StreamTextType) -> Any:
        """
        the old cyaml needs special setup, and therefore the stream
        """
        if self.Constructor is None:
            if 'full' in self.typ:
                raise YAMLError(
                     "\nyou can only use yaml=YAML(typ='full') for dumping\n",  # NOQA
                )
        if self.Parser is not CParser:
            if self.Reader is None:
                self.Reader = ruamel.reader.Reader
            if self.Scanner is None:
                self.Scanner = ruamel.scanner.Scanner
            self.reader.stream = stream
        else:
            if self.Reader is not None:
                if self.Scanner is None:
                    self.Scanner = ruamel.scanner.Scanner
                self.Parser = ruamel.parser.Parser
                self.reader.stream = stream
            elif self.Scanner is not None:
                if self.Reader is None:
                    self.Reader = ruamel.reader.Reader
                self.Parser = ruamel.parser.Parser
                self.reader.stream = stream
            else:
                # combined C level reader>scanner>parser
                # does some calls to the resolver, e.g. BaseResolver.descend_resolver
                # if you just initialise the CParser, to much of resolver.py
                # is actually used
                rslvr = self.Resolver
                # if rslvr is ruamel.resolver.VersionedResolver:
                #     rslvr = ruamel.resolver.Resolver

                class XLoader(self.Parser, self.Constructor, rslvr):  # type: ignore
                    def __init__(
                        selfx,
                        stream: StreamTextType,
                        version: Optional[VersionType] = self.version,
                        preserve_quotes: Optional[bool] = None,
                    ) -> None:
                        # NOQA
                        CParser.__init__(selfx, stream)
                        selfx._parser = selfx._composer = selfx
                        self.Constructor.__init__(selfx, loader=selfx)
                        selfx.allow_duplicate_keys = self.allow_duplicate_keys
                        rslvr.__init__(selfx, version=version, loadumper=selfx)

                self._stream = stream
                loader = XLoader(stream)
                return loader, loader
        return self.constructor, self.parser

    def emit(self, events: Any, stream: Any) -> None:
        """
        Emit YAML parsing events into a stream.
        If stream is None, return the produced string instead.
        """
        _, _, emitter = self.get_serializer_representer_emitter(stream, None)
        try:
            for event in events:
                emitter.emit(event)
        finally:
            try:
                emitter.dispose()
            except AttributeError:
                raise

    def serialize(self, node: Any, stream: Optional[StreamType]) -> Any:
        """
        Serialize a representation tree into a YAML stream.
        If stream is None, return the produced string instead.
        """
        self.serialize_all([node], stream)

    def serialize_all(self, nodes: Any, stream: Optional[StreamType]) -> Any:
        """
        Serialize a sequence of representation trees into a YAML stream.
        If stream is None, return the produced string instead.
        """
        serializer, _, emitter = self.get_serializer_representer_emitter(stream, None)
        try:
            serializer.open()
            for node in nodes:
                serializer.serialize(node)
            serializer.close()
        finally:
            try:
                emitter.dispose()
            except AttributeError:
                raise

    def dump(
        self: Any, data: Union[Path, StreamType], stream: Any = None, *, transform: Any = None,
    ) -> Any:
        if self._context_manager:
            if not self._output:
                raise TypeError('Missing output stream while dumping from context manager')
            if transform is not None:
                x = self.__class__.__name__
                raise TypeError(
                    f'{x}.dump() in the context manager cannot have transform keyword',
                )
            self._context_manager.dump(data)
        else:  # old style
            if stream is None:
                raise TypeError('Need a stream argument when not dumping from context manager')
            return self.dump_all([data], stream, transform=transform)

    def dump_all(
        self, documents: Any, stream: Union[Path, StreamType], *, transform: Any = None,
    ) -> Any:
        if self._context_manager:
            raise NotImplementedError
        self._output = stream
        self._context_manager = YAMLContextManager(self, transform=transform)
        for data in documents:
            self._context_manager.dump(data)
        self._context_manager.teardown_output()
        self._output = None
        self._context_manager = None

    def Xdump_all(self, documents: Any, stream: Any, *, transform: Any = None) -> Any:
        """
        Serialize a sequence of Python objects into a YAML stream.
        """
        if not hasattr(stream, 'write') and hasattr(stream, 'open'):
            # pathlib.Path() instance
            with stream.open('w') as fp:
                return self.dump_all(documents, fp, transform=transform)
        # The stream should have the methods `write` and possibly `flush`.
        if self.top_level_colon_align is True:
            tlca: Any = max([len(str(x)) for x in documents[0]])
        else:
            tlca = self.top_level_colon_align
        if transform is not None:
            fstream = stream
            if self.encoding is None:
                stream = StringIO()
            else:
                stream = BytesIO()
        serializer, representer, emitter = self.get_serializer_representer_emitter(
            stream, tlca,
        )
        try:
            self.serializer.open()
            for data in documents:
                try:
                    self.representer.represent(data)
                except AttributeError:
                    # nprint(dir(dumper._representer))
                    raise
            self.serializer.close()
        finally:
            try:
                self.emitter.dispose()
            except AttributeError:
                raise
                # self.dumper.dispose()  # cyaml
            delattr(self, '_serializer')
            delattr(self, '_emitter')
        if transform:
            val = stream.getvalue()
            if self.encoding:
                val = val.decode(self.encoding)
            if fstream is None:
                transform(val)
            else:
                fstream.write(transform(val))
        return None

    def get_serializer_representer_emitter(self, stream: StreamType, tlca: Any) -> Any:
        # we have only .Serializer to deal with (vs .Reader & .Scanner), much simpler
        if self.Emitter is not CEmitter:
            if self.Serializer is None:
                self.Serializer = ruamel.serializer.Serializer
            self.emitter.stream = stream
            self.emitter.top_level_colon_align = tlca
            if self.scalar_after_indicator is not None:
                self.emitter.scalar_after_indicator = self.scalar_after_indicator
            return self.serializer, self.representer, self.emitter
        if self.Serializer is not None:
            # cannot set serializer with CEmitter
            self.Emitter = ruamel.emitter.Emitter
            self.emitter.stream = stream
            self.emitter.top_level_colon_align = tlca
            if self.scalar_after_indicator is not None:
                self.emitter.scalar_after_indicator = self.scalar_after_indicator
            return self.serializer, self.representer, self.emitter
        # C routines

        rslvr = (
            ruamel.resolver.BaseResolver
            if 'base' in self.typ
            else ruamel.resolver.Resolver
        )

        class XDumper(CEmitter, self.Representer, rslvr):  # type: ignore
            def __init__(
                selfx: StreamType,
                stream: Any,
                default_style: Any = None,
                default_flow_style: Any = None,
                canonical: Optional[bool] = None,
                indent: Optional[int] = None,
                width: Optional[int] = None,
                allow_unicode: Optional[bool] = None,
                line_break: Any = None,
                encoding: Any = None,
                explicit_start: Optional[bool] = None,
                explicit_end: Optional[bool] = None,
                version: Any = None,
                tags: Any = None,
                block_seq_indent: Any = None,
                top_level_colon_align: Any = None,
                prefix_colon: Any = None,
            ) -> None:
                # NOQA
                CEmitter.__init__(
                    selfx,
                    stream,
                    canonical=canonical,
                    indent=indent,
                    width=width,
                    encoding=encoding,
                    allow_unicode=allow_unicode,
                    line_break=line_break,
                    explicit_start=explicit_start,
                    explicit_end=explicit_end,
                    version=version,
                    tags=tags,
                )
                selfx._emitter = selfx._serializer = selfx._representer = selfx
                self.Representer.__init__(
                    selfx, default_style=default_style, default_flow_style=default_flow_style,
                )
                rslvr.__init__(selfx)

        self._stream = stream
        dumper = XDumper(
            stream,
            default_style=self.default_style,
            default_flow_style=self.default_flow_style,
            canonical=self.canonical,
            indent=self.old_indent,
            width=self.width,
            allow_unicode=self.allow_unicode,
            line_break=self.line_break,
            encoding=self.encoding,
            explicit_start=self.explicit_start,
            explicit_end=self.explicit_end,
            version=self.version,
            tags=self.tags,
        )
        self._emitter = self._serializer = dumper
        return dumper, dumper, dumper

    # basic types
    def map(self, **kw: Any) -> Any:
        if 'rt' in self.typ:
            return CommentedMap(**kw)
        else:
            return dict(**kw)

    def seq(self, *args: Any) -> Any:
        if 'rt' in self.typ:
            return CommentedSeq(*args)
        else:
            return list(*args)

    # helpers
    def official_plug_ins(self) -> Any:
        """search for list of subdirs that are plug-ins, if __file__ is not available, e.g.
        single file installers that are not properly emulating a file-system (issue 324)
        no plug-ins will be found. If any are packaged, you know which file that are
        and you can explicitly provide it during instantiation:
            yaml = ruamel.YAML(plug_ins=['ruamel/yaml/jinja2/__plug_in__'])
        """
        try:
            bd = os.path.dirname(__file__)
        except NameError:
            return []
        gpbd = os.path.dirname(os.path.dirname(bd))
        res = [x.replace(gpbd, "")[1:-3] for x in glob.glob(bd + '/*/__plug_in__.py')]
        return res

    def register_class(self, cls: Any) -> Any:
        """
        register a class for dumping/loading
        - if it has attribute yaml_tag use that to register, else use class name
        - if it has methods to_yaml/from_yaml use those to dump/load else dump attributes
          as mapping
        """
        tag = getattr(cls, 'yaml_tag', '!' + cls.__name__)
        try:
            self.representer.add_representer(cls, cls.to_yaml)
        except AttributeError:

            def t_y(representer: Any, data: Any) -> Any:
                return representer.represent_yaml_object(
                    tag, data, cls, flow_style=representer.default_flow_style,
                )

            self.representer.add_representer(cls, t_y)
        try:
            self.constructor.add_constructor(tag, cls.from_yaml)
        except AttributeError:

            def f_y(constructor: Any, node: Any) -> Any:
                return constructor.construct_yaml_object(node, cls)

            self.constructor.add_constructor(tag, f_y)
        return cls

    # ### context manager

    def __enter__(self) -> Any:
        self._context_manager = YAMLContextManager(self)
        return self

    def __exit__(
        self,
        typ: Optional[Type[BaseException]],
        value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if typ:
            nprint('typ', typ)
        self._context_manager.teardown_output()
        # self._context_manager.teardown_input()
        self._context_manager = None

    # ### backwards compatibility
    def _indent(self, mapping: Any = None, sequence: Any = None, offset: Any = None) -> None:
        if mapping is not None:
            self.map_indent = mapping
        if sequence is not None:
            self.sequence_indent = sequence
        if offset is not None:
            self.sequence_dash_offset = offset

    @property
    def version(self) -> Optional[Tuple[int, int]]:
        return self._version

    @version.setter
    def version(self, val: VersionType) -> None:
        if val is None:
            self._version = val
            return
        elif isinstance(val, str):
            sval = tuple(int(x) for x in val.split('.'))
        elif isinstance(val, (list, tuple)):
            sval = tuple(int(x) for x in val)
        elif isinstance(val, Version):
            sval = (val.major, val.minor)
        else:
            raise TypeError(f'unknown version type {type(val)}')
        assert len(sval) == 2, f'version can only have major.minor, got {val}'
        assert sval[0] == 1, f'version major part can only be 1, got {val}'
        assert sval[1] in [1, 2], f'version minor part can only be 2 or 1, got {val}'
        self._version = sval

    @property
    def tags(self) -> Any:
        return self._tags

    @tags.setter
    def tags(self, val: Any) -> None:
        self._tags = val

    @property
    def indent(self) -> Any:
        return self._indent

    @indent.setter
    def indent(self, val: Any) -> None:
        self.old_indent = val

    @property
    def block_seq_indent(self) -> Any:
        return self.sequence_dash_offset

    @block_seq_indent.setter
    def block_seq_indent(self, val: Any) -> None:
        self.sequence_dash_offset = val

    def compact(self, seq_seq: Any = None, seq_map: Any = None) -> None:
        self.compact_seq_seq = seq_seq
        self.compact_seq_map = seq_map


class YAMLContextManager:
    def __init__(self, yaml: Any, transform: Any = None) -> None:
        # used to be: (Any, Optional[Callable]) -> None
        self._yaml = yaml
        self._output_inited = False
        self._output_path = None
        self._output = self._yaml._output
        self._transform = transform

        # self._input_inited = False
        # self._input = input
        # self._input_path = None
        # self._transform = yaml.transform
        # self._fstream = None

        if not hasattr(self._output, 'write') and hasattr(self._output, 'open'):
            # pathlib.Path() instance, open with the same mode
            self._output_path = self._output
            self._output = self._output_path.open('w')

        # if not hasattr(self._stream, 'write') and hasattr(stream, 'open'):
        # if not hasattr(self._input, 'read') and hasattr(self._input, 'open'):
        #    # pathlib.Path() instance, open with the same mode
        #    self._input_path = self._input
        #    self._input = self._input_path.open('r')

        if self._transform is not None:
            self._fstream = self._output
            if self._yaml.encoding is None:
                self._output = StringIO()
            else:
                self._output = BytesIO()

    def teardown_output(self) -> None:
        if self._output_inited:
            self._yaml.serializer.close()
        else:
            return
        try:
            self._yaml.emitter.dispose()
        except AttributeError:
            raise
            # self.dumper.dispose()  # cyaml
        try:
            delattr(self._yaml, '_serializer')
            delattr(self._yaml, '_emitter')
        except AttributeError:
            raise
        if self._transform:
            val = self._output.getvalue()
            if self._yaml.encoding:
                val = val.decode(self._yaml.encoding)
            if self._fstream is None:
                self._transform(val)
            else:
                self._fstream.write(self._transform(val))
                self._fstream.flush()
                self._output = self._fstream  # maybe not necessary
        if self._output_path is not None:
            self._output.close()

    def init_output(self, first_data: Any) -> None:
        if self._yaml.top_level_colon_align is True:
            tlca: Any = max([len(str(x)) for x in first_data])
        else:
            tlca = self._yaml.top_level_colon_align
        self._yaml.get_serializer_representer_emitter(self._output, tlca)
        self._yaml.serializer.open()
        self._output_inited = True

    def dump(self, data: Any) -> None:
        if not self._output_inited:
            self.init_output(data)
        try:
            self._yaml.representer.represent(data)
        except AttributeError:
            # nprint(dir(dumper._representer))
            raise

    # def teardown_input(self):
    #     pass
    #
    # def init_input(self):
    #     # set the constructor and parser on YAML() instance
    #     self._yaml.get_constructor_parser(stream)
    #
    # def load(self):
    #     if not self._input_inited:
    #         self.init_input()
    #     try:
    #         while self._yaml.constructor.check_data():
    #             yield self._yaml.constructor.get_data()
    #     finally:
    #         parser.dispose()
    #         try:
    #             self._reader.reset_reader()  # type: ignore
    #         except AttributeError:
    #             pass
    #         try:
    #             self._scanner.reset_scanner()  # type: ignore
    #         except AttributeError:
    #             pass


def yaml_object(yml: Any) -> Any:
    """ decorator for classes that needs to dump/load objects
    The tag for such objects is taken from the class attribute yaml_tag (or the
    class name in lowercase in case unavailable)
    If methods to_yaml and/or from_yaml are available, these are called for dumping resp.
    loading, default routines (dumping a mapping of the attributes) used otherwise.
    """

    def yo_deco(cls: Any) -> Any:
        tag = getattr(cls, 'yaml_tag', '!' + cls.__name__)
        try:
            yml.representer.add_representer(cls, cls.to_yaml)
        except AttributeError:

            def t_y(representer: Any, data: Any) -> Any:
                return representer.represent_yaml_object(
                    tag, data, cls, flow_style=representer.default_flow_style,
                )

            yml.representer.add_representer(cls, t_y)
        try:
            yml.constructor.add_constructor(tag, cls.from_yaml)
        except AttributeError:

            def f_y(constructor: Any, node: Any) -> Any:
                return constructor.construct_yaml_object(node, cls)

            yml.constructor.add_constructor(tag, f_y)
        return cls

    return yo_deco


########################################################################################
def warn_deprecation(fun: Any, method: Any, arg: str = '') -> None:
    warnings.warn(
        f'\n{fun} will be removed, use\n\n  yaml=YAML({arg})\n  yaml.{method}(...)\n\ninstead',  # NOQA
        PendingDeprecationWarning,  # this will show when testing with pytest/tox
        stacklevel=3,
    )


def error_deprecation(fun: Any, method: Any, arg: str = '', comment: str = 'instead of') -> None:  # NOQA
    import inspect

    s = f'\n"{fun}()" has been removed, use\n\n  yaml = YAML({arg})\n  yaml.{method}(...)\n\n{comment}'  # NOQA
    try:
        info = inspect.getframeinfo(inspect.stack()[2][0])
        context = '' if info.code_context is None else "".join(info.code_context)
        s += f' file "{info.filename}", line {info.lineno}\n\n{context}'
    except Exception as e:
        _ = e
    s += '\n'
    if sys.version_info < (3, 10):
        raise AttributeError(s)
    else:
        raise AttributeError(s, name=None)


_error_dep_arg = "typ='rt'"
_error_dep_comment = "and register any classes that you use, or check the tag attribute on the loaded data,\ninstead of"  # NOQA

########################################################################################


def scan(stream: StreamTextType, Loader: Any = Loader) -> Any:
    """
    Scan a YAML stream and produce scanning tokens.
    """
    error_deprecation('scan', 'scan', arg=_error_dep_arg, comment=_error_dep_comment)


def parse(stream: StreamTextType, Loader: Any = Loader) -> Any:
    """
    Parse a YAML stream and produce parsing events.
    """
    error_deprecation('parse', 'parse', arg=_error_dep_arg, comment=_error_dep_comment)


def compose(stream: StreamTextType, Loader: Any = Loader) -> Any:
    """
    Parse the first YAML document in a stream
    and produce the corresponding representation tree.
    """
    error_deprecation('compose', 'compose', arg=_error_dep_arg, comment=_error_dep_comment)


def compose_all(stream: StreamTextType, Loader: Any = Loader) -> Any:
    """
    Parse all YAML documents in a stream
    and produce corresponding representation trees.
    """
    error_deprecation('compose', 'compose', arg=_error_dep_arg, comment=_error_dep_comment)


def load(
    stream: Any, Loader: Any = None, version: Any = None, preserve_quotes: Any = None,
) -> Any:
    """
    Parse the first YAML document in a stream
    and produce the corresponding Python object.
    """
    error_deprecation('load', 'load', arg=_error_dep_arg, comment=_error_dep_comment)


def load_all(
    stream: Any, Loader: Any = None, version: Any = None, preserve_quotes: Any = None,
) -> Any:
    # NOQA
    """
    Parse all YAML documents in a stream
    and produce corresponding Python objects.
    """
    error_deprecation('load_all', 'load_all', arg=_error_dep_arg, comment=_error_dep_comment)


def safe_load(stream: StreamTextType, version: Optional[VersionType] = None) -> Any:
    """
    Parse the first YAML document in a stream
    and produce the corresponding Python object.
    Resolve only basic YAML tags.
    """
    error_deprecation('safe_load', 'load', arg="typ='safe', pure=True")


def safe_load_all(stream: StreamTextType, version: Optional[VersionType] = None) -> Any:
    """
    Parse all YAML documents in a stream
    and produce corresponding Python objects.
    Resolve only basic YAML tags.
    """
    error_deprecation('safe_load_all', 'load_all', arg="typ='safe', pure=True")


def round_trip_load(
    stream: StreamTextType,
    version: Optional[VersionType] = None,
    preserve_quotes: Optional[bool] = None,
) -> Any:
    """
    Parse the first YAML document in a stream
    and produce the corresponding Python object.
    Resolve only basic YAML tags.
    """
    error_deprecation('round_trip_load_all', 'load')


def round_trip_load_all(
    stream: StreamTextType,
    version: Optional[VersionType] = None,
    preserve_quotes: Optional[bool] = None,
) -> Any:
    """
    Parse all YAML documents in a stream
    and produce corresponding Python objects.
    Resolve only basic YAML tags.
    """
    error_deprecation('round_trip_load_all', 'load_all')


def emit(
    events: Any,
    stream: Optional[StreamType] = None,
    Dumper: Any = Dumper,
    canonical: Optional[bool] = None,
    indent: Union[int, None] = None,
    width: Optional[int] = None,
    allow_unicode: Optional[bool] = None,
    line_break: Any = None,
) -> Any:
    # NOQA
    """
    Emit YAML parsing events into a stream.
    If stream is None, return the produced string instead.
    """
    error_deprecation('emit', 'emit', arg="typ='safe', pure=True")


enc = None


def serialize_all(
    nodes: Any,
    stream: Optional[StreamType] = None,
    Dumper: Any = Dumper,
    canonical: Any = None,
    indent: Optional[int] = None,
    width: Optional[int] = None,
    allow_unicode: Optional[bool] = None,
    line_break: Any = None,
    encoding: Any = enc,
    explicit_start: Optional[bool] = None,
    explicit_end: Optional[bool] = None,
    version: Optional[VersionType] = None,
    tags: Any = None,
) -> Any:
    # NOQA
    """
    Serialize a sequence of representation trees into a YAML stream.
    If stream is None, return the produced string instead.
    """
    error_deprecation('serialize_all', 'serialize_all', arg="typ='safe', pure=True")


def serialize(
    node: Any, stream: Optional[StreamType] = None, Dumper: Any = Dumper, **kwds: Any,
) -> Any:
    """
    Serialize a representation tree into a YAML stream.
    If stream is None, return the produced string instead.
    """
    error_deprecation('serialize', 'serialize', arg="typ='safe', pure=True")


def dump_all(
    documents: Any,
    stream: Optional[StreamType] = None,
    Dumper: Any = Dumper,
    default_style: Any = None,
    default_flow_style: Any = None,
    canonical: Optional[bool] = None,
    indent: Optional[int] = None,
    width: Optional[int] = None,
    allow_unicode: Optional[bool] = None,
    line_break: Any = None,
    encoding: Any = enc,
    explicit_start: Optional[bool] = None,
    explicit_end: Optional[bool] = None,
    version: Any = None,
    tags: Any = None,
    block_seq_indent: Any = None,
    top_level_colon_align: Any = None,
    prefix_colon: Any = None,
) -> Any:
    # NOQA
    """
    Serialize a sequence of Python objects into a YAML stream.
    If stream is None, return the produced string instead.
    """
    error_deprecation('dump_all', 'dump_all', arg="typ='unsafe', pure=True")


def dump(
    data: Any,
    stream: Optional[StreamType] = None,
    Dumper: Any = Dumper,
    default_style: Any = None,
    default_flow_style: Any = None,
    canonical: Optional[bool] = None,
    indent: Optional[int] = None,
    width: Optional[int] = None,
    allow_unicode: Optional[bool] = None,
    line_break: Any = None,
    encoding: Any = enc,
    explicit_start: Optional[bool] = None,
    explicit_end: Optional[bool] = None,
    version: Optional[VersionType] = None,
    tags: Any = None,
    block_seq_indent: Any = None,
) -> Any:
    # NOQA
    """
    Serialize a Python object into a YAML stream.
    If stream is None, return the produced string instead.

    default_style ∈ None, '', '"', "'", '|', '>'

    """
    error_deprecation('dump', 'dump', arg="typ='unsafe', pure=True")


def safe_dump(data: Any, stream: Optional[StreamType] = None, **kwds: Any) -> Any:
    """
    Serialize a Python object into a YAML stream.
    Produce only basic YAML tags.
    If stream is None, return the produced string instead.
    """
    error_deprecation('safe_dump', 'dump', arg="typ='safe', pure=True")


def round_trip_dump(
    data: Any,
    stream: Optional[StreamType] = None,
    Dumper: Any = RoundTripDumper,
    default_style: Any = None,
    default_flow_style: Any = None,
    canonical: Optional[bool] = None,
    indent: Optional[int] = None,
    width: Optional[int] = None,
    allow_unicode: Optional[bool] = None,
    line_break: Any = None,
    encoding: Any = enc,
    explicit_start: Optional[bool] = None,
    explicit_end: Optional[bool] = None,
    version: Optional[VersionType] = None,
    tags: Any = None,
    block_seq_indent: Any = None,
    top_level_colon_align: Any = None,
    prefix_colon: Any = None,
) -> Any:
    allow_unicode = True if allow_unicode is None else allow_unicode
    error_deprecation('round_trip_dump', 'dump')


# Loader/Dumper are no longer composites, to get to the associated
# Resolver()/Representer(), etc., you need to instantiate the class


def add_implicit_resolver(
    tag: Any,
    regexp: Any,
    first: Any = None,
    Loader: Any = None,
    Dumper: Any = None,
    resolver: Any = Resolver,
) -> None:
    """
    Add an implicit scalar detector.
    If an implicit scalar value matches the given regexp,
    the corresponding tag is assigned to the scalar.
    first is a sequence of possible initial characters or None.
    """
    if Loader is None and Dumper is None:
        resolver.add_implicit_resolver(tag, regexp, first)
        return
    if Loader:
        if hasattr(Loader, 'add_implicit_resolver'):
            Loader.add_implicit_resolver(tag, regexp, first)
        elif issubclass(
            Loader, (BaseLoader, SafeLoader, ruamel.loader.Loader, RoundTripLoader),
        ):
            Resolver.add_implicit_resolver(tag, regexp, first)
        else:
            raise NotImplementedError
    if Dumper:
        if hasattr(Dumper, 'add_implicit_resolver'):
            Dumper.add_implicit_resolver(tag, regexp, first)
        elif issubclass(
            Dumper, (BaseDumper, SafeDumper, ruamel.dumper.Dumper, RoundTripDumper),
        ):
            Resolver.add_implicit_resolver(tag, regexp, first)
        else:
            raise NotImplementedError


# this code currently not tested
def add_path_resolver(
    tag: Any,
    path: Any,
    kind: Any = None,
    Loader: Any = None,
    Dumper: Any = None,
    resolver: Any = Resolver,
) -> None:
    """
    Add a path based resolver for the given tag.
    A path is a list of keys that forms a path
    to a node in the representation tree.
    Keys can be string values, integers, or None.
    """
    if Loader is None and Dumper is None:
        resolver.add_path_resolver(tag, path, kind)
        return
    if Loader:
        if hasattr(Loader, 'add_path_resolver'):
            Loader.add_path_resolver(tag, path, kind)
        elif issubclass(
            Loader, (BaseLoader, SafeLoader, ruamel.loader.Loader, RoundTripLoader),
        ):
            Resolver.add_path_resolver(tag, path, kind)
        else:
            raise NotImplementedError
    if Dumper:
        if hasattr(Dumper, 'add_path_resolver'):
            Dumper.add_path_resolver(tag, path, kind)
        elif issubclass(
            Dumper, (BaseDumper, SafeDumper, ruamel.dumper.Dumper, RoundTripDumper),
        ):
            Resolver.add_path_resolver(tag, path, kind)
        else:
            raise NotImplementedError


def add_constructor(
    tag: Any, object_constructor: Any, Loader: Any = None, constructor: Any = Constructor,
) -> None:
    """
    Add an object constructor for the given tag.
    object_onstructor is a function that accepts a Loader instance
    and a node object and produces the corresponding Python object.
    """
    if Loader is None:
        constructor.add_constructor(tag, object_constructor)
    else:
        if hasattr(Loader, 'add_constructor'):
            Loader.add_constructor(tag, object_constructor)
            return
        if issubclass(Loader, BaseLoader):
            BaseConstructor.add_constructor(tag, object_constructor)
        elif issubclass(Loader, SafeLoader):
            SafeConstructor.add_constructor(tag, object_constructor)
        elif issubclass(Loader, Loader):
            Constructor.add_constructor(tag, object_constructor)
        elif issubclass(Loader, RoundTripLoader):
            RoundTripConstructor.add_constructor(tag, object_constructor)
        else:
            raise NotImplementedError


def add_multi_constructor(
    tag_prefix: Any, multi_constructor: Any, Loader: Any = None, constructor: Any = Constructor,  # NOQA
) -> None:
    """
    Add a multi-constructor for the given tag prefix.
    Multi-constructor is called for a node if its tag starts with tag_prefix.
    Multi-constructor accepts a Loader instance, a tag suffix,
    and a node object and produces the corresponding Python object.
    """
    if Loader is None:
        constructor.add_multi_constructor(tag_prefix, multi_constructor)
    else:
        if False and hasattr(Loader, 'add_multi_constructor'):
            Loader.add_multi_constructor(tag_prefix, constructor)
            return
        if issubclass(Loader, BaseLoader):
            BaseConstructor.add_multi_constructor(tag_prefix, multi_constructor)
        elif issubclass(Loader, SafeLoader):
            SafeConstructor.add_multi_constructor(tag_prefix, multi_constructor)
        elif issubclass(Loader, ruamel.loader.Loader):
            Constructor.add_multi_constructor(tag_prefix, multi_constructor)
        elif issubclass(Loader, RoundTripLoader):
            RoundTripConstructor.add_multi_constructor(tag_prefix, multi_constructor)
        else:
            raise NotImplementedError


def add_representer(
    data_type: Any, object_representer: Any, Dumper: Any = None, representer: Any = Representer,  # NOQA
) -> None:
    """
    Add a representer for the given type.
    object_representer is a function accepting a Dumper instance
    and an instance of the given data type
    and producing the corresponding representation node.
    """
    if Dumper is None:
        representer.add_representer(data_type, object_representer)
    else:
        if hasattr(Dumper, 'add_representer'):
            Dumper.add_representer(data_type, object_representer)
            return
        if issubclass(Dumper, BaseDumper):
            BaseRepresenter.add_representer(data_type, object_representer)
        elif issubclass(Dumper, SafeDumper):
            SafeRepresenter.add_representer(data_type, object_representer)
        elif issubclass(Dumper, Dumper):
            Representer.add_representer(data_type, object_representer)
        elif issubclass(Dumper, RoundTripDumper):
            RoundTripRepresenter.add_representer(data_type, object_representer)
        else:
            raise NotImplementedError


# this code currently not tested
def add_multi_representer(
    data_type: Any, multi_representer: Any, Dumper: Any = None, representer: Any = Representer,
) -> None:
    """
    Add a representer for the given type.
    multi_representer is a function accepting a Dumper instance
    and an instance of the given data type or subtype
    and producing the corresponding representation node.
    """
    if Dumper is None:
        representer.add_multi_representer(data_type, multi_representer)
    else:
        if hasattr(Dumper, 'add_multi_representer'):
            Dumper.add_multi_representer(data_type, multi_representer)
            return
        if issubclass(Dumper, BaseDumper):
            BaseRepresenter.add_multi_representer(data_type, multi_representer)
        elif issubclass(Dumper, SafeDumper):
            SafeRepresenter.add_multi_representer(data_type, multi_representer)
        elif issubclass(Dumper, Dumper):
            Representer.add_multi_representer(data_type, multi_representer)
        elif issubclass(Dumper, RoundTripDumper):
            RoundTripRepresenter.add_multi_representer(data_type, multi_representer)
        else:
            raise NotImplementedError


class YAMLObjectMetaclass(type):
    """
    The metaclass for YAMLObject.
    """

    def __init__(cls, name: Any, bases: Any, kwds: Any) -> None:
        super().__init__(name, bases, kwds)
        if 'yaml_tag' in kwds and kwds['yaml_tag'] is not None:
            cls.yaml_constructor.add_constructor(cls.yaml_tag, cls.from_yaml)  # type: ignore
            cls.yaml_representer.add_representer(cls, cls.to_yaml)  # type: ignore


class YAMLObject(with_metaclass(YAMLObjectMetaclass)):  # type: ignore
    """
    An object that can dump itself to a YAML stream
    and load itself from a YAML stream.
    """

    __slots__ = ()  # no direct instantiation, so allow immutable subclasses

    yaml_constructor = Constructor
    yaml_representer = Representer

    yaml_tag: Any = None
    yaml_flow_style: Any = None

    @classmethod
    def from_yaml(cls, constructor: Any, node: Any) -> Any:
        """
        Convert a representation node to a Python object.
        """
        return constructor.construct_yaml_object(node, cls)

    @classmethod
    def to_yaml(cls, representer: Any, data: Any) -> Any:
        """
        Convert a Python object to a representation node.
        """
        return representer.represent_yaml_object(
            cls.yaml_tag, data, cls, flow_style=cls.yaml_flow_style,
        )
