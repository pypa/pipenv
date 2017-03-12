/* Refrences:
 * https://lists.samba.org/archive/samba-technical/2009-February/063079.html
 * http://stackoverflow.com/questions/4139405/#4139811
 * https://code.google.com/p/openpgm/source/browse/trunk/openpgm/pgm/getifaddrs.c
 */

#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <net/if.h>
#include <netinet/in.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/sockio.h>

#include "ifaddrs.h"

#define MAX(x,y) ((x)>(y)?(x):(y))
#define SIZE(p) MAX((p).ss_len,sizeof(p))


static struct sockaddr *
sa_dup (struct sockaddr *sa1)
{
    struct sockaddr *sa2;
    size_t sz = sizeof(sa1);
    sa2 = (struct sockaddr *) calloc(1,sz);
    memcpy(sa2,sa1,sz);
    return(sa2);
}


void freeifaddrs (struct ifaddrs *ifp)
{
    if (NULL == ifp) return;
    free(ifp->ifa_name);
    free(ifp->ifa_addr);
    free(ifp->ifa_netmask);
    free(ifp->ifa_dstaddr);
    freeifaddrs(ifp->ifa_next);
    free(ifp);
}


int getifaddrs (struct ifaddrs **ifap)
{
    int sd = -1;
    char *ccp, *ecp;
    struct lifconf ifc;
    struct lifreq *ifr;
    struct lifnum lifn;
    struct ifaddrs *cifa = NULL; /* current */
    struct ifaddrs *pifa = NULL; /* previous */
    const size_t IFREQSZ = sizeof(struct lifreq);

    sd = socket(AF_INET, SOCK_STREAM, 0);
    if (sd < 0)
        goto error;

    ifc.lifc_buf = NULL;
    *ifap = NULL;
    /* find how much memory to allocate for the SIOCGLIFCONF call */
    lifn.lifn_family = AF_UNSPEC;
    lifn.lifn_flags = 0;
    if (ioctl(sd, SIOCGLIFNUM, &lifn) < 0)
        goto error;

    /* Sun and Apple code likes to pad the interface count here in case interfaces
     * are coming up between calls */
    lifn.lifn_count += 4;

    ifc.lifc_family = AF_UNSPEC;
    ifc.lifc_len = lifn.lifn_count * sizeof(struct lifreq);
    ifc.lifc_buf = calloc(1, ifc.lifc_len);
    if (ioctl(sd, SIOCGLIFCONF, &ifc) < 0)
        goto error;

    ccp = (char *)ifc.lifc_req;
    ecp = ccp + ifc.lifc_len;

    while (ccp < ecp) {

        ifr = (struct lifreq *) ccp;
        cifa = (struct ifaddrs *) calloc(1, sizeof(struct ifaddrs));
        cifa->ifa_next = NULL;
        cifa->ifa_name = strdup(ifr->lifr_name);

        if (pifa == NULL) *ifap = cifa; /* first one */
        else pifa->ifa_next = cifa;

        if (ioctl(sd, SIOCGLIFADDR, ifr, IFREQSZ) < 0)
            goto error;
        cifa->ifa_addr = sa_dup((struct sockaddr*)&ifr->lifr_addr);

        if (ioctl(sd, SIOCGLIFNETMASK, ifr, IFREQSZ) < 0)
            goto error;
        cifa->ifa_netmask = sa_dup((struct sockaddr*)&ifr->lifr_addr);

        cifa->ifa_flags = 0;
        cifa->ifa_dstaddr = NULL;

        if (0 == ioctl(sd, SIOCGLIFFLAGS, ifr)) /* optional */
            cifa->ifa_flags = ifr->lifr_flags;

        if (ioctl(sd, SIOCGLIFDSTADDR, ifr, IFREQSZ) < 0) {
            if (0 == ioctl(sd, SIOCGLIFBRDADDR, ifr, IFREQSZ))
                cifa->ifa_dstaddr = sa_dup((struct sockaddr*)&ifr->lifr_addr);
        }
        else cifa->ifa_dstaddr = sa_dup((struct sockaddr*)&ifr->lifr_addr);

        pifa = cifa;
        ccp += IFREQSZ;
    }
    free(ifc.lifc_buf);
    close(sd);
    return 0;
error:
    if (ifc.lifc_buf != NULL)
        free(ifc.lifc_buf);
    if (sd != -1)
        close(sd);
    return (-1);
}
