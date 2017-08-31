#include <ws2tcpip.h>

PCSTR
WSAAPI
inet_ntop(
    __in                                INT             Family,
    __in                                PVOID           pAddr,
    __out_ecount(StringBufSize)         PSTR            pStringBuf,
    __in                                size_t          StringBufSize
);