/* Reference: https://lists.samba.org/archive/samba-technical/2009-February/063079.html */


#ifndef __IFADDRS_H___
#define __IFADDRS_H___

#include <sys/socket.h>
#include <net/if.h>

#undef  ifa_dstaddr
#undef  ifa_broadaddr
#define ifa_broadaddr ifa_dstaddr

struct ifaddrs {
    struct ifaddrs  *ifa_next;
    char            *ifa_name;
    unsigned int     ifa_flags;
    struct sockaddr *ifa_addr;
    struct sockaddr *ifa_netmask;
    struct sockaddr *ifa_dstaddr;
};

extern int getifaddrs(struct ifaddrs **);
extern void freeifaddrs(struct ifaddrs *);

#endif