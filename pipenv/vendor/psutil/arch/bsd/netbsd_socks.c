/*
 * Copyright (c) 2009, Giampaolo Rodola'.
 * Copyright (c) 2015, Ryo ONODERA.
 * All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include <Python.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/sysctl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <string.h>
#include <sys/cdefs.h>
#include <arpa/inet.h>
#include <sys/queue.h>
#include <sys/un.h>
#include <sys/file.h>

// a signaler for connections without an actual status
int PSUTIL_CONN_NONE = 128;

// address family filter
enum af_filter {
    INET,
    INET4,
    INET6,
    TCP,
    TCP4,
    TCP6,
    UDP,
    UDP4,
    UDP6,
    UNIX,
    ALL,
};

// kinfo_file results
struct kif {
    SLIST_ENTRY(kif) kifs;
    struct kinfo_file *kif;
};

// kinfo_file results list
SLIST_HEAD(kifhead, kif) kihead = SLIST_HEAD_INITIALIZER(kihead);


// kinfo_pcb results
struct kpcb {
    SLIST_ENTRY(kpcb) kpcbs;
    struct kinfo_pcb *kpcb;
};

// kinfo_pcb results list
SLIST_HEAD(kpcbhead, kpcb) kpcbhead = SLIST_HEAD_INITIALIZER(kpcbhead);

static void psutil_kiflist_init(void);
static void psutil_kiflist_clear(void);
static void psutil_kpcblist_init(void);
static void psutil_kpcblist_clear(void);
static int psutil_get_files(void);
static int psutil_get_sockets(const char *name);
static int psutil_get_info(int aff);


// Initialize kinfo_file results list.
static void
psutil_kiflist_init(void) {
    SLIST_INIT(&kihead);
    return;
}


// Clear kinfo_file results list.
static void
psutil_kiflist_clear(void) {
     while (!SLIST_EMPTY(&kihead)) {
             SLIST_REMOVE_HEAD(&kihead, kifs);
     }

    return;
}


// Initialize kinof_pcb result list.
static void
psutil_kpcblist_init(void) {
    SLIST_INIT(&kpcbhead);
    return;
}


// Clear kinof_pcb result list.
static void
psutil_kpcblist_clear(void) {
     while (!SLIST_EMPTY(&kpcbhead)) {
             SLIST_REMOVE_HEAD(&kpcbhead, kpcbs);
     }

    return;
}


// Get all open files including socket.
static int
psutil_get_files(void) {
    size_t len;
    int mib[6];
    char *buf;
    off_t offset;
    int j;

    mib[0] = CTL_KERN;
    mib[1] = KERN_FILE2;
    mib[2] = KERN_FILE_BYFILE;
    mib[3] = 0;
    mib[4] = sizeof(struct kinfo_file);
    mib[5] = 0;

    if (sysctl(mib, 6, NULL, &len, NULL, 0) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }

    offset = len % sizeof(off_t);
    mib[5] = len / sizeof(struct kinfo_file);

    if ((buf = malloc(len + offset)) == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    if (sysctl(mib, 6, buf + offset, &len, NULL, 0) == -1) {
        free(buf);
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }

    len /= sizeof(struct kinfo_file);
    struct kinfo_file *ki = (struct kinfo_file *)(buf + offset);

    for (j = 0; j < len; j++) {
        struct kif *kif = malloc(sizeof(struct kif));
        kif->kif = &ki[j];
        SLIST_INSERT_HEAD(&kihead, kif, kifs);
    }

    /*
    // debug
    struct kif *k;
    SLIST_FOREACH(k, &kihead, kifs) {
            printf("%d\n", k->kif->ki_pid);
    }
    */

    return 0;
}


// Get open sockets.
static int
psutil_get_sockets(const char *name) {
    size_t namelen;
    int mib[8];
    int ret, j;
    struct kinfo_pcb *pcb;
    size_t len;

    memset(mib, 0, sizeof(mib));

    if (sysctlnametomib(name, mib, &namelen) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }

    if (sysctl(mib, __arraycount(mib), NULL, &len, NULL, 0) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }

    if ((pcb = malloc(len)) == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    memset(pcb, 0, len);

    mib[6] = sizeof(*pcb);
    mib[7] = len / sizeof(*pcb);

    if (sysctl(mib, __arraycount(mib), pcb, &len, NULL, 0) == -1) {
        free(pcb);
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }

    len /= sizeof(struct kinfo_pcb);
    struct kinfo_pcb *kp = (struct kinfo_pcb *)pcb;

    for (j = 0; j < len; j++) {
        struct kpcb *kpcb = malloc(sizeof(struct kpcb));
        kpcb->kpcb = &kp[j];
        SLIST_INSERT_HEAD(&kpcbhead, kpcb, kpcbs);
    }

    /*
    // debug
    struct kif *k;
    struct kpcb *k;
    SLIST_FOREACH(k, &kpcbhead, kpcbs) {
            printf("ki_type: %d\n", k->kpcb->ki_type);
            printf("ki_family: %d\n", k->kpcb->ki_family);
    }
    */

    return 0;
}


// Collect open file and connections.
static int
psutil_get_info(int aff) {
    switch (aff) {
        case INET:
            if (psutil_get_sockets("net.inet.tcp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet.udp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.tcp6.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.udp6.pcblist") != 0)
                return -1;
            break;
        case INET4:
            if (psutil_get_sockets("net.inet.tcp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet.udp.pcblist") != 0)
                return -1;
            break;
        case INET6:
            if (psutil_get_sockets("net.inet6.tcp6.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.udp6.pcblist") != 0)
                return -1;
            break;
        case TCP:
            if (psutil_get_sockets("net.inet.tcp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.tcp6.pcblist") != 0)
                return -1;
            break;
        case TCP4:
            if (psutil_get_sockets("net.inet.tcp.pcblist") != 0)
                return -1;
            break;
        case TCP6:
            if (psutil_get_sockets("net.inet6.tcp6.pcblist") != 0)
                return -1;
            break;
        case UDP:
            if (psutil_get_sockets("net.inet.udp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.udp6.pcblist") != 0)
                return -1;
            break;
        case UDP4:
            if (psutil_get_sockets("net.inet.udp.pcblist") != 0)
                return -1;
            break;
        case UDP6:
            if (psutil_get_sockets("net.inet6.udp6.pcblist") != 0)
                return -1;
            break;
        case UNIX:
            if (psutil_get_sockets("net.local.stream.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.local.seqpacket.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.local.dgram.pcblist") != 0)
                return -1;
            break;
        case ALL:
            if (psutil_get_sockets("net.inet.tcp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet.udp.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.tcp6.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.inet6.udp6.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.local.stream.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.local.seqpacket.pcblist") != 0)
                return -1;
            if (psutil_get_sockets("net.local.dgram.pcblist") != 0)
                return -1;
            break;
    }

    return 0;
}


/*
 * Return system-wide connections (unless a pid != -1 is passed).
 */
PyObject *
psutil_net_connections(PyObject *self, PyObject *args) {
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;
    pid_t pid;

    if (py_retlist == NULL)
        return NULL;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    psutil_kiflist_init();
    psutil_kpcblist_init();
    if (psutil_get_files() != 0)
        goto error;
    if (psutil_get_info(ALL) != 0)
        goto error;

    struct kif *k;
    SLIST_FOREACH(k, &kihead, kifs) {
        struct kpcb *kp;
        if ((pid != -1) && (k->kif->ki_pid != pid))
            continue;
        SLIST_FOREACH(kp, &kpcbhead, kpcbs) {
            if (k->kif->ki_fdata != kp->kpcb->ki_sockaddr)
                continue;
            char laddr[PATH_MAX];
            char raddr[PATH_MAX];
            int32_t lport;
            int32_t rport;
            int32_t status;

            // IPv4 or IPv6
            if ((kp->kpcb->ki_family == AF_INET) ||
                    (kp->kpcb->ki_family == AF_INET6)) {

                if (kp->kpcb->ki_family == AF_INET) {
                    // IPv4
                    struct sockaddr_in *sin_src =
                        (struct sockaddr_in *)&kp->kpcb->ki_src;
                    struct sockaddr_in *sin_dst =
                        (struct sockaddr_in *)&kp->kpcb->ki_dst;
                    // source addr and port
                    inet_ntop(AF_INET, &sin_src->sin_addr, laddr,
                              sizeof(laddr));
                    lport = ntohs(sin_src->sin_port);
                    // remote addr and port
                    inet_ntop(AF_INET, &sin_dst->sin_addr, raddr,
                              sizeof(raddr));
                    rport = ntohs(sin_dst->sin_port);
                }
                else {
                    // IPv6
                    struct sockaddr_in6 *sin6_src =
                        (struct sockaddr_in6 *)&kp->kpcb->ki_src;
                    struct sockaddr_in6 *sin6_dst =
                        (struct sockaddr_in6 *)&kp->kpcb->ki_dst;
                    // local addr and port
                    inet_ntop(AF_INET6, &sin6_src->sin6_addr, laddr,
                              sizeof(laddr));
                    lport = ntohs(sin6_src->sin6_port);
                    // remote addr and port
                    inet_ntop(AF_INET6, &sin6_dst->sin6_addr, raddr,
                              sizeof(raddr));
                    rport = ntohs(sin6_dst->sin6_port);
                }

                // status
                if (kp->kpcb->ki_type == SOCK_STREAM)
                    status = kp->kpcb->ki_tstate;
                else
                    status = PSUTIL_CONN_NONE;

                // build addr tuple
                py_laddr = Py_BuildValue("(si)", laddr, lport);
                if (! py_laddr)
                    goto error;
                if (rport != 0)
                    py_raddr = Py_BuildValue("(si)", raddr, rport);
                else
                    py_raddr = Py_BuildValue("()");
                if (! py_raddr)
                    goto error;
            }
            else if (kp->kpcb->ki_family == AF_UNIX) {
                // UNIX sockets
                struct sockaddr_un *sun_src =
                    (struct sockaddr_un *)&kp->kpcb->ki_src;
                struct sockaddr_un *sun_dst =
                    (struct sockaddr_un *)&kp->kpcb->ki_dst;
                strcpy(laddr, sun_src->sun_path);
                strcpy(raddr, sun_dst->sun_path);
                status = PSUTIL_CONN_NONE;
                // TODO: handle unicode
                py_laddr = Py_BuildValue("s", laddr);
                if (! py_laddr)
                    goto error;
                // TODO: handle unicode
                py_raddr = Py_BuildValue("s", raddr);
                if (! py_raddr)
                    goto error;
            }

            // append tuple to list
            py_tuple = Py_BuildValue(
                "(iiiNNii)",
                k->kif->ki_fd,
                kp->kpcb->ki_family,
                kp->kpcb->ki_type,
                py_laddr,
                py_raddr,
                status,
                k->kif->ki_pid);
            if (! py_tuple)
                goto error;
            if (PyList_Append(py_retlist, py_tuple))
                goto error;
            Py_DECREF(py_tuple);
        }
    }

    psutil_kiflist_clear();
    psutil_kpcblist_clear();
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_laddr);
    Py_XDECREF(py_raddr);
    return 0;
}
