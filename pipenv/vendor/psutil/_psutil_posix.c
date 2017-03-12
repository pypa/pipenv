/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Functions specific to all POSIX compliant platforms.
 */

#include <Python.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>

#ifdef PSUTIL_SUNOS10
    #include "arch/solaris/v10/ifaddrs.h"
#else
    #include <ifaddrs.h>
#endif

#if defined(PSUTIL_LINUX)
    #include <netdb.h>
    #include <linux/if_packet.h>
#elif defined(PSUTIL_BSD) || defined(PSUTIL_OSX)
    #include <netdb.h>
    #include <netinet/in.h>
    #include <net/if_dl.h>
    #include <sys/sockio.h>
    #include <net/if_media.h>
    #include <net/if.h>
#elif defined(PSUTIL_SUNOS)
    #include <netdb.h>
    #include <sys/sockio.h>
#endif


/*
 * Given a PID return process priority as a Python integer.
 */
static PyObject *
psutil_posix_getpriority(PyObject *self, PyObject *args) {
    long pid;
    int priority;
    errno = 0;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

#ifdef PSUTIL_OSX
    priority = getpriority(PRIO_PROCESS, (id_t)pid);
#else
    priority = getpriority(PRIO_PROCESS, pid);
#endif
    if (errno != 0)
        return PyErr_SetFromErrno(PyExc_OSError);
    return Py_BuildValue("i", priority);
}


/*
 * Given a PID and a value change process priority.
 */
static PyObject *
psutil_posix_setpriority(PyObject *self, PyObject *args) {
    long pid;
    int priority;
    int retval;

    if (! PyArg_ParseTuple(args, "li", &pid, &priority))
        return NULL;

#ifdef PSUTIL_OSX
    retval = setpriority(PRIO_PROCESS, (id_t)pid, priority);
#else
    retval = setpriority(PRIO_PROCESS, pid, priority);
#endif
    if (retval == -1)
        return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}


/*
 * Translate a sockaddr struct into a Python string.
 * Return None if address family is not AF_INET* or AF_PACKET.
 */
static PyObject *
psutil_convert_ipaddr(struct sockaddr *addr, int family) {
    char buf[NI_MAXHOST];
    int err;
    int addrlen;
    size_t n;
    size_t len;
    const char *data;
    char *ptr;

    if (addr == NULL) {
        Py_INCREF(Py_None);
        return Py_None;
    }
    else if (family == AF_INET || family == AF_INET6) {
        if (family == AF_INET)
            addrlen = sizeof(struct sockaddr_in);
        else
            addrlen = sizeof(struct sockaddr_in6);
        err = getnameinfo(addr, addrlen, buf, sizeof(buf), NULL, 0,
                          NI_NUMERICHOST);
        if (err != 0) {
            // XXX we get here on FreeBSD when processing 'lo' / AF_INET6
            // broadcast. Not sure what to do other than returning None.
            // ifconfig does not show anything BTW.
            //PyErr_Format(PyExc_RuntimeError, gai_strerror(err));
            //return NULL;
            Py_INCREF(Py_None);
            return Py_None;
        }
        else {
            return Py_BuildValue("s", buf);
        }
    }
#ifdef PSUTIL_LINUX
    else if (family == AF_PACKET) {
        struct sockaddr_ll *lladdr = (struct sockaddr_ll *)addr;
        len = lladdr->sll_halen;
        data = (const char *)lladdr->sll_addr;
    }
#elif defined(PSUTIL_BSD) || defined(PSUTIL_OSX)
    else if (addr->sa_family == AF_LINK) {
        // Note: prior to Python 3.4 socket module does not expose
        // AF_LINK so we'll do.
        struct sockaddr_dl *dladdr = (struct sockaddr_dl *)addr;
        len = dladdr->sdl_alen;
        data = LLADDR(dladdr);
    }
#endif
    else {
        // unknown family
        Py_INCREF(Py_None);
        return Py_None;
    }

    // AF_PACKET or AF_LINK
    if (len > 0) {
        ptr = buf;
        for (n = 0; n < len; ++n) {
            sprintf(ptr, "%02x:", data[n] & 0xff);
            ptr += 3;
        }
        *--ptr = '\0';
        return Py_BuildValue("s", buf);
    }
    else {
        Py_INCREF(Py_None);
        return Py_None;
    }
}


/*
 * Return NICs information a-la ifconfig as a list of tuples.
 * TODO: on Solaris we won't get any MAC address.
 */
static PyObject*
psutil_net_if_addrs(PyObject* self, PyObject* args) {
    struct ifaddrs *ifaddr, *ifa;
    int family;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_address = NULL;
    PyObject *py_netmask = NULL;
    PyObject *py_broadcast = NULL;
    PyObject *py_ptp = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (getifaddrs(&ifaddr) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
        if (!ifa->ifa_addr)
            continue;
        family = ifa->ifa_addr->sa_family;
        py_address = psutil_convert_ipaddr(ifa->ifa_addr, family);
        // If the primary address can't be determined just skip it.
        // I've never seen this happen on Linux but I did on FreeBSD.
        if (py_address == Py_None)
            continue;
        if (py_address == NULL)
            goto error;
        py_netmask = psutil_convert_ipaddr(ifa->ifa_netmask, family);
        if (py_netmask == NULL)
            goto error;

        if (ifa->ifa_flags & IFF_BROADCAST) {
            py_broadcast = psutil_convert_ipaddr(ifa->ifa_broadaddr, family);
            Py_INCREF(Py_None);
            py_ptp = Py_None;
        }
        else if (ifa->ifa_flags & IFF_POINTOPOINT) {
            py_ptp = psutil_convert_ipaddr(ifa->ifa_dstaddr, family);
            Py_INCREF(Py_None);
            py_broadcast = Py_None;
        }
        else {
            Py_INCREF(Py_None);
            Py_INCREF(Py_None);
            py_broadcast = Py_None;
            py_ptp = Py_None;
        }

        if ((py_broadcast == NULL) || (py_ptp == NULL))
            goto error;
        py_tuple = Py_BuildValue(
            "(siOOOO)",
            ifa->ifa_name,
            family,
            py_address,
            py_netmask,
            py_broadcast,
            py_ptp
        );

        if (! py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
        Py_DECREF(py_address);
        Py_DECREF(py_netmask);
        Py_DECREF(py_broadcast);
        Py_DECREF(py_ptp);
    }

    freeifaddrs(ifaddr);
    return py_retlist;

error:
    if (ifaddr != NULL)
        freeifaddrs(ifaddr);
    Py_DECREF(py_retlist);
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_address);
    Py_XDECREF(py_netmask);
    Py_XDECREF(py_broadcast);
    Py_XDECREF(py_ptp);
    return NULL;
}


/*
 * Return NIC MTU. References:
 * http://www.i-scream.org/libstatgrab/
 */
static PyObject *
psutil_net_if_mtu(PyObject *self, PyObject *args) {
    char *nic_name;
    int sock = 0;
    int ret;
#ifdef PSUTIL_SUNOS10
    struct lifreq lifr;
#else
    struct ifreq ifr;
#endif

    if (! PyArg_ParseTuple(args, "s", &nic_name))
        return NULL;

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1)
        goto error;

#ifdef PSUTIL_SUNOS10
    strncpy(lifr.lifr_name, nic_name, sizeof(lifr.lifr_name));
    ret = ioctl(sock, SIOCGIFMTU, &lifr);
#else
    strncpy(ifr.ifr_name, nic_name, sizeof(ifr.ifr_name));
    ret = ioctl(sock, SIOCGIFMTU, &ifr);
#endif
    if (ret == -1)
        goto error;
    close(sock);

#ifdef PSUTIL_SUNOS10
    return Py_BuildValue("i", lifr.lifr_mtu);
#else
    return Py_BuildValue("i", ifr.ifr_mtu);
#endif

error:
    if (sock != 0)
        close(sock);
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


/*
 * Inspect NIC flags, returns a bool indicating whether the NIC is
 * running. References:
 * http://www.i-scream.org/libstatgrab/
 */
static PyObject *
psutil_net_if_flags(PyObject *self, PyObject *args) {
    char *nic_name;
    int sock = 0;
    int ret;
    struct ifreq ifr;

    if (! PyArg_ParseTuple(args, "s", &nic_name))
        return NULL;

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1)
        goto error;

    strncpy(ifr.ifr_name, nic_name, sizeof(ifr.ifr_name));
    ret = ioctl(sock, SIOCGIFFLAGS, &ifr);
    if (ret == -1)
        goto error;

    close(sock);
    if ((ifr.ifr_flags & IFF_UP) != 0)
        return Py_BuildValue("O", Py_True);
    else
        return Py_BuildValue("O", Py_False);

error:
    if (sock != 0)
        close(sock);
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


/*
 * net_if_stats() OSX/BSD implementation.
 */
#if defined(PSUTIL_BSD) || defined(PSUTIL_OSX)

int psutil_get_nic_speed(int ifm_active) {
    // Determine NIC speed. Taken from:
    // http://www.i-scream.org/libstatgrab/
    // Assuming only ETHER devices
    switch(IFM_TYPE(ifm_active)) {
        case IFM_ETHER:
            switch(IFM_SUBTYPE(ifm_active)) {
#if defined(IFM_HPNA_1) && ((!defined(IFM_10G_LR)) \
    || (IFM_10G_LR != IFM_HPNA_1))
                // HomePNA 1.0 (1Mb/s)
                case(IFM_HPNA_1):
                    return 1;
#endif
                // 10 Mbit
                case(IFM_10_T):  // 10BaseT - RJ45
                case(IFM_10_2):  // 10Base2 - Thinnet
                case(IFM_10_5):  // 10Base5 - AUI
                case(IFM_10_STP):  // 10BaseT over shielded TP
                case(IFM_10_FL):  // 10baseFL - Fiber
                    return 10;
                // 100 Mbit
                case(IFM_100_TX):  // 100BaseTX - RJ45
                case(IFM_100_FX):  // 100BaseFX - Fiber
                case(IFM_100_T4):  // 100BaseT4 - 4 pair cat 3
                case(IFM_100_VG):  // 100VG-AnyLAN
                case(IFM_100_T2):  // 100BaseT2
                    return 100;
                // 1000 Mbit
                case(IFM_1000_SX):  // 1000BaseSX - multi-mode fiber
                case(IFM_1000_LX):  // 1000baseLX - single-mode fiber
                case(IFM_1000_CX):  // 1000baseCX - 150ohm STP
#if defined(IFM_1000_TX) && !defined(PSUTIL_OPENBSD)
                // FreeBSD 4 and others (but NOT OpenBSD) -> #define IFM_1000_T in net/if_media.h
                case(IFM_1000_TX):
#endif
#ifdef IFM_1000_FX
                case(IFM_1000_FX):
#endif
#ifdef IFM_1000_T
                case(IFM_1000_T):
#endif
                    return 1000;
#if defined(IFM_10G_SR) || defined(IFM_10G_LR) || defined(IFM_10G_CX4) \
         || defined(IFM_10G_T)
#ifdef IFM_10G_SR
                case(IFM_10G_SR):
#endif
#ifdef IFM_10G_LR
                case(IFM_10G_LR):
#endif
#ifdef IFM_10G_CX4
                case(IFM_10G_CX4):
#endif
#ifdef IFM_10G_TWINAX
                case(IFM_10G_TWINAX):
#endif
#ifdef IFM_10G_TWINAX_LONG
                case(IFM_10G_TWINAX_LONG):
#endif
#ifdef IFM_10G_T
                case(IFM_10G_T):
#endif
                    return 10000;
#endif
#if defined(IFM_2500_SX)
#ifdef IFM_2500_SX
                case(IFM_2500_SX):
#endif
                    return 2500;
#endif // any 2.5GBit stuff...
                // We don't know what it is
                default:
                    return 0;
            }
            break;

#ifdef IFM_TOKEN
        case IFM_TOKEN:
            switch(IFM_SUBTYPE(ifm_active)) {
                case IFM_TOK_STP4:  // Shielded twisted pair 4m - DB9
                case IFM_TOK_UTP4:  // Unshielded twisted pair 4m - RJ45
                    return 4;
                case IFM_TOK_STP16:  // Shielded twisted pair 16m - DB9
                case IFM_TOK_UTP16:  // Unshielded twisted pair 16m - RJ45
                    return 16;
#if defined(IFM_TOK_STP100) || defined(IFM_TOK_UTP100)
#ifdef IFM_TOK_STP100
                case IFM_TOK_STP100:  // Shielded twisted pair 100m - DB9
#endif
#ifdef IFM_TOK_UTP100
                case IFM_TOK_UTP100:  // Unshielded twisted pair 100m - RJ45
#endif
                    return 100;
#endif
                // We don't know what it is
                default:
                    return 0;
            }
            break;
#endif

#ifdef IFM_FDDI
        case IFM_FDDI:
            switch(IFM_SUBTYPE(ifm_active)) {
                // We don't know what it is
                default:
                    return 0;
            }
            break;
#endif
        case IFM_IEEE80211:
            switch(IFM_SUBTYPE(ifm_active)) {
                case IFM_IEEE80211_FH1:  // Frequency Hopping 1Mbps
                case IFM_IEEE80211_DS1:  // Direct Sequence 1Mbps
                    return 1;
                case IFM_IEEE80211_FH2:  // Frequency Hopping 2Mbps
                case IFM_IEEE80211_DS2:  // Direct Sequence 2Mbps
                    return 2;
                case IFM_IEEE80211_DS5:  // Direct Sequence 5Mbps
                    return 5;
                case IFM_IEEE80211_DS11:  // Direct Sequence 11Mbps
                    return 11;
                case IFM_IEEE80211_DS22:  // Direct Sequence 22Mbps
                    return 22;
                // We don't know what it is
                default:
                    return 0;
            }
            break;

        default:
            return 0;
    }
}


/*
 * Return stats about a particular network interface.
 * References:
 * http://www.i-scream.org/libstatgrab/
 */
static PyObject *
psutil_net_if_duplex_speed(PyObject *self, PyObject *args) {
    char *nic_name;
    int sock = 0;
    int ret;
    int duplex;
    int speed;
    struct ifreq ifr;
    struct ifmediareq ifmed;

    if (! PyArg_ParseTuple(args, "s", &nic_name))
        return NULL;

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1)
        goto error;
    strncpy(ifr.ifr_name, nic_name, sizeof(ifr.ifr_name));

    // speed / duplex
    memset(&ifmed, 0, sizeof(struct ifmediareq));
    strlcpy(ifmed.ifm_name, nic_name, sizeof(ifmed.ifm_name));
    ret = ioctl(sock, SIOCGIFMEDIA, (caddr_t)&ifmed);
    if (ret == -1) {
        speed = 0;
        duplex = 0;
    }
    else {
        speed = psutil_get_nic_speed(ifmed.ifm_active);
        if ((ifmed.ifm_active | IFM_FDX) == ifmed.ifm_active)
            duplex = 2;
        else if ((ifmed.ifm_active | IFM_HDX) == ifmed.ifm_active)
            duplex = 1;
        else
            duplex = 0;
    }

    close(sock);
    return Py_BuildValue("[ii]", duplex, speed);

error:
    if (sock != 0)
        close(sock);
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}
#endif  // net_if_stats() OSX/BSD implementation


/*
 * define the psutil C module methods and initialize the module.
 */
static PyMethodDef
PsutilMethods[] = {
    {"getpriority", psutil_posix_getpriority, METH_VARARGS,
     "Return process priority"},
    {"setpriority", psutil_posix_setpriority, METH_VARARGS,
     "Set process priority"},
    {"net_if_addrs", psutil_net_if_addrs, METH_VARARGS,
     "Retrieve NICs information"},
    {"net_if_mtu", psutil_net_if_mtu, METH_VARARGS,
     "Retrieve NIC MTU"},
    {"net_if_flags", psutil_net_if_flags, METH_VARARGS,
     "Retrieve NIC flags"},
#if defined(PSUTIL_BSD) || defined(PSUTIL_OSX)
    {"net_if_duplex_speed", psutil_net_if_duplex_speed, METH_VARARGS,
     "Return NIC stats."},
#endif
    {NULL, NULL, 0, NULL}
};

struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
#define GETSTATE(m) (&_state)
#endif

#if PY_MAJOR_VERSION >= 3

static int
psutil_posix_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}


static int
psutil_posix_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "psutil_posix",
    NULL,
    sizeof(struct module_state),
    PsutilMethods,
    NULL,
    psutil_posix_traverse,
    psutil_posix_clear,
    NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit__psutil_posix(void)

#else
#define INITERROR return

void init_psutil_posix(void)
#endif
{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("_psutil_posix", PsutilMethods);
#endif

#if defined(PSUTIL_BSD) || defined(PSUTIL_OSX) || defined(PSUTIL_SUNOS)
    PyModule_AddIntConstant(module, "AF_LINK", AF_LINK);
#endif

    if (module == NULL)
        INITERROR;
#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
