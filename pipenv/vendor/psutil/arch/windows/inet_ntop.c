#include "inet_ntop.h"

// From: https://memset.wordpress.com/2010/10/09/inet_ntop-for-win32/
PCSTR
WSAAPI
inet_ntop(__in INT Family,
          __in PVOID pAddr,
          __out_ecount(StringBufSize) PSTR pStringBuf,
          __in size_t StringBufSize) {
    DWORD dwAddressLength = 0;
    struct sockaddr_storage srcaddr;
    struct sockaddr_in *srcaddr4 = (struct sockaddr_in*) &srcaddr;
    struct sockaddr_in6 *srcaddr6 = (struct sockaddr_in6*) &srcaddr;

    memset(&srcaddr, 0, sizeof(struct sockaddr_storage));
    srcaddr.ss_family = Family;

    if (Family == AF_INET)
    {
        dwAddressLength = sizeof(struct sockaddr_in);
        memcpy(&(srcaddr4->sin_addr), pAddr, sizeof(struct in_addr));
    } else if (Family == AF_INET6)
    {
        dwAddressLength = sizeof(struct sockaddr_in6);
        memcpy(&(srcaddr6->sin6_addr), pAddr, sizeof(struct in6_addr));
    } else {
        return NULL;
    }

    if (WSAAddressToString((LPSOCKADDR) &srcaddr,
                           dwAddressLength,
                           0,
                           pStringBuf,
                           (LPDWORD) &StringBufSize) != 0) {
        return NULL;
    }
    return pStringBuf;
}
