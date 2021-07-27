# Type hints copied from the typeshed project under the Apache License 2.0
# https://github.com/python/typeshed/blob/64c85cdd449ccaff90b546676220c9ecfa6e697f/LICENSE

import sys
from types import TracebackType
from typing import (
    IO,
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    ContextManager,
    Iterator,
    Optional,
    Type,
    TypeVar,
    overload,
)
from typing_extensions import ParamSpec, Protocol

# contextlib2 API adaptation notes:
# * the various 'if True:' guards replace sys.version checks in the original
#   typeshed file (those APIs are available on all supported versions)
# * deliberately omitted APIs are listed in `dev/mypy.allowlist`
#   (e.g. deprecated experimental APIs that never graduated to the stdlib)

AbstractContextManager = ContextManager
if True:
    AbstractAsyncContextManager = AsyncContextManager

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_io = TypeVar("_T_io", bound=Optional[IO[str]])
_F = TypeVar("_F", bound=Callable[..., Any])
_P = ParamSpec("_P")

_ExitFunc = Callable[[Optional[Type[BaseException]], Optional[BaseException], Optional[TracebackType]], bool]
_CM_EF = TypeVar("_CM_EF", ContextManager[Any], _ExitFunc)

class _GeneratorContextManager(ContextManager[_T_co]):
    def __call__(self, func: _F) -> _F: ...

# type ignore to deal with incomplete ParamSpec support in mypy
def contextmanager(func: Callable[_P, Iterator[_T]]) -> Callable[_P, _GeneratorContextManager[_T]]: ...  # type: ignore

if True:
    def asynccontextmanager(func: Callable[_P, AsyncIterator[_T]]) -> Callable[_P, AsyncContextManager[_T]]: ...  # type: ignore

class _SupportsClose(Protocol):
    def close(self) -> object: ...

_SupportsCloseT = TypeVar("_SupportsCloseT", bound=_SupportsClose)

class closing(ContextManager[_SupportsCloseT]):
    def __init__(self, thing: _SupportsCloseT) -> None: ...

if True:
    class _SupportsAclose(Protocol):
        async def aclose(self) -> object: ...
    _SupportsAcloseT = TypeVar("_SupportsAcloseT", bound=_SupportsAclose)
    class aclosing(AsyncContextManager[_SupportsAcloseT]):
        def __init__(self, thing: _SupportsAcloseT) -> None: ...
    _AF = TypeVar("_AF", bound=Callable[..., Awaitable[Any]])
    class AsyncContextDecorator:
        def __call__(self, func: _AF) -> _AF: ...

class suppress(ContextManager[None]):
    def __init__(self, *exceptions: Type[BaseException]) -> None: ...
    def __exit__(
        self, exctype: Optional[Type[BaseException]], excinst: Optional[BaseException], exctb: Optional[TracebackType]
    ) -> bool: ...

class redirect_stdout(ContextManager[_T_io]):
    def __init__(self, new_target: _T_io) -> None: ...

class redirect_stderr(ContextManager[_T_io]):
    def __init__(self, new_target: _T_io) -> None: ...

class ContextDecorator:
    def __call__(self, func: _F) -> _F: ...

_U = TypeVar("_U", bound=ExitStack)

class ExitStack(ContextManager[ExitStack]):
    def __init__(self) -> None: ...
    def enter_context(self, cm: ContextManager[_T]) -> _T: ...
    def push(self, exit: _CM_EF) -> _CM_EF: ...
    def callback(self, callback: Callable[..., Any], *args: Any, **kwds: Any) -> Callable[..., Any]: ...
    def pop_all(self: _U) -> _U: ...
    def close(self) -> None: ...
    def __enter__(self: _U) -> _U: ...
    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> bool: ...

if True:
    _S = TypeVar("_S", bound=AsyncExitStack)

    _ExitCoroFunc = Callable[[Optional[Type[BaseException]], Optional[BaseException], Optional[TracebackType]], Awaitable[bool]]
    _CallbackCoroFunc = Callable[..., Awaitable[Any]]
    _ACM_EF = TypeVar("_ACM_EF", AsyncContextManager[Any], _ExitCoroFunc)
    class AsyncExitStack(AsyncContextManager[AsyncExitStack]):
        def __init__(self) -> None: ...
        def enter_context(self, cm: ContextManager[_T]) -> _T: ...
        def enter_async_context(self, cm: AsyncContextManager[_T]) -> Awaitable[_T]: ...
        def push(self, exit: _CM_EF) -> _CM_EF: ...
        def push_async_exit(self, exit: _ACM_EF) -> _ACM_EF: ...
        def callback(self, callback: Callable[..., Any], *args: Any, **kwds: Any) -> Callable[..., Any]: ...
        def push_async_callback(self, callback: _CallbackCoroFunc, *args: Any, **kwds: Any) -> _CallbackCoroFunc: ...
        def pop_all(self: _S) -> _S: ...
        def aclose(self) -> Awaitable[None]: ...
        def __aenter__(self: _S) -> Awaitable[_S]: ...
        def __aexit__(
            self,
            __exc_type: Optional[Type[BaseException]],
            __exc_value: Optional[BaseException],
            __traceback: Optional[TracebackType],
        ) -> Awaitable[bool]: ...

if True:
    class nullcontext(AbstractContextManager[_T]):
        enter_result: _T
        @overload
        def __init__(self: nullcontext[None], enter_result: None = ...) -> None: ...
        @overload
        def __init__(self: nullcontext[_T], enter_result: _T) -> None: ...
        def __enter__(self) -> _T: ...
        def __exit__(self, *exctype: Any) -> bool: ...
