/*
 * Copyright (c) 2009, Giampaolo Rodola'.
 * All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include <Python.h>
#include <sys/user.h>
#include <sys/file.h>
#include <sys/socketvar.h>    // for struct xsocket
#include <sys/un.h>
#include <sys/unpcb.h>
#include <sys/types.h>
#include <sys/sysctl.h>
#include <netinet/in.h>   // for xinpcb struct
#include <netinet/in_systm.h>
#include <netinet/ip.h>
#include <netinet/in_pcb.h>
#include <netinet/tcp.h>
#include <netinet/tcp_timer.h>
#include <netinet/tcp_var.h>   // for struct xtcpcb
#include <netinet/tcp_fsm.h>   // for TCP connection states
#include <arpa/inet.h>         // for inet_ntop()
#include <net/if_media.h>
#include <libutil.h>

#include "../../_psutil_common.h"


#define HASHSIZE 1009
// a signaler for connections without an actual status
static int PSUTIL_CONN_NONE = 128;
static struct xfile *psutil_xfiles;
static int psutil_nxfiles;


// The tcplist fetching and walking is borrowed from netstat/inet.c.
static char *
psutil_fetch_tcplist(void) {
    char *buf;
    size_t len;

    for (;;) {
        if (sysctlbyname("net.inet.tcp.pcblist", NULL, &len, NULL, 0) < 0) {
            PyErr_SetFromErrno(PyExc_OSError);
            return NULL;
        }
        buf = malloc(len);
        if (buf == NULL) {
            PyErr_NoMemory();
            return NULL;
        }
        if (sysctlbyname("net.inet.tcp.pcblist", buf, &len, NULL, 0) < 0) {
            free(buf);
            PyErr_SetFromErrno(PyExc_OSError);
            return NULL;
        }
        return buf;
    }
}


static int
psutil_sockaddr_port(int family, struct sockaddr_storage *ss) {
    struct sockaddr_in6 *sin6;
    struct sockaddr_in *sin;

    if (family == AF_INET) {
        sin = (struct sockaddr_in *)ss;
        return (sin->sin_port);
    }
    else {
        sin6 = (struct sockaddr_in6 *)ss;
        return (sin6->sin6_port);
    }
}


static void *
psutil_sockaddr_addr(int family, struct sockaddr_storage *ss) {
    struct sockaddr_in6 *sin6;
    struct sockaddr_in *sin;

    if (family == AF_INET) {
        sin = (struct sockaddr_in *)ss;
        return (&sin->sin_addr);
    }
    else {
        sin6 = (struct sockaddr_in6 *)ss;
        return (&sin6->sin6_addr);
    }
}


static socklen_t
psutil_sockaddr_addrlen(int family) {
    if (family == AF_INET)
        return (sizeof(struct in_addr));
    else
        return (sizeof(struct in6_addr));
}


static int
psutil_sockaddr_matches(int family, int port, void *pcb_addr,
                        struct sockaddr_storage *ss) {
    if (psutil_sockaddr_port(family, ss) != port)
        return (0);
    return (memcmp(psutil_sockaddr_addr(family, ss), pcb_addr,
                   psutil_sockaddr_addrlen(family)) == 0);
}


static struct tcpcb *
psutil_search_tcplist(char *buf, struct kinfo_file *kif) {
    struct tcpcb *tp;
    struct inpcb *inp;
    struct xinpgen *xig, *oxig;
    struct xsocket *so;

    oxig = xig = (struct xinpgen *)buf;
    for (xig = (struct xinpgen *)((char *)xig + xig->xig_len);
            xig->xig_len > sizeof(struct xinpgen);
            xig = (struct xinpgen *)((char *)xig + xig->xig_len)) {
        tp = &((struct xtcpcb *)xig)->xt_tp;
        inp = &((struct xtcpcb *)xig)->xt_inp;
        so = &((struct xtcpcb *)xig)->xt_socket;

        if (so->so_type != kif->kf_sock_type ||
                so->xso_family != kif->kf_sock_domain ||
                so->xso_protocol != kif->kf_sock_protocol)
            continue;

        if (kif->kf_sock_domain == AF_INET) {
            if (!psutil_sockaddr_matches(
                    AF_INET, inp->inp_lport, &inp->inp_laddr,
                    &kif->kf_sa_local))
                continue;
            if (!psutil_sockaddr_matches(
                    AF_INET, inp->inp_fport, &inp->inp_faddr,
                    &kif->kf_sa_peer))
                continue;
        } else {
            if (!psutil_sockaddr_matches(
                    AF_INET6, inp->inp_lport, &inp->in6p_laddr,
                    &kif->kf_sa_local))
                continue;
            if (!psutil_sockaddr_matches(
                    AF_INET6, inp->inp_fport, &inp->in6p_faddr,
                    &kif->kf_sa_peer))
                continue;
        }

        return (tp);
    }
    return NULL;
}


int
psutil_populate_xfiles() {
    size_t len;

    if ((psutil_xfiles = malloc(len = sizeof *psutil_xfiles)) == NULL) {
        PyErr_NoMemory();
        return 0;
    }
    while (sysctlbyname("kern.file", psutil_xfiles, &len, 0, 0) == -1) {
        if (errno != ENOMEM) {
            PyErr_SetFromErrno(0);
            return 0;
        }
        len *= 2;
        if ((psutil_xfiles = realloc(psutil_xfiles, len)) == NULL) {
            PyErr_NoMemory();
            return 0;
        }
    }
    if (len > 0 && psutil_xfiles->xf_size != sizeof *psutil_xfiles) {
        PyErr_Format(PyExc_RuntimeError, "struct xfile size mismatch");
        return 0;
    }
    psutil_nxfiles = len / sizeof *psutil_xfiles;
    return 1;
}


int
psutil_get_pid_from_sock(int sock_hash) {
    struct xfile *xf;
    int hash, n;
    for (xf = psutil_xfiles, n = 0; n < psutil_nxfiles; ++n, ++xf) {
        if (xf->xf_data == NULL)
            continue;
        hash = (int)((uintptr_t)xf->xf_data % HASHSIZE);
        if (sock_hash == hash)
            return xf->xf_pid;
    }
    return -1;
}


// Reference:
// https://gitorious.org/freebsd/freebsd/source/
//     f1d6f4778d2044502209708bc167c05f9aa48615:usr.bin/sockstat/sockstat.c
int psutil_gather_inet(int proto, PyObject *py_retlist) {
    struct xinpgen *xig, *exig;
    struct xinpcb *xip;
    struct xtcpcb *xtp;
    struct inpcb *inp;
    struct xsocket *so;
    const char *varname = NULL;
    size_t len, bufsize;
    void *buf;
    int hash;
    int retry;
    int type;

    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;

    switch (proto) {
        case IPPROTO_TCP:
            varname = "net.inet.tcp.pcblist";
            type = SOCK_STREAM;
            break;
        case IPPROTO_UDP:
            varname = "net.inet.udp.pcblist";
            type = SOCK_DGRAM;
            break;
    }

    buf = NULL;
    bufsize = 8192;
    retry = 5;
    do {
        for (;;) {
            buf = realloc(buf, bufsize);
            if (buf == NULL)
                continue;  // XXX
            len = bufsize;
            if (sysctlbyname(varname, buf, &len, NULL, 0) == 0)
                break;
            if (errno != ENOMEM) {
                PyErr_SetFromErrno(0);
                goto error;
            }
            bufsize *= 2;
        }
        xig = (struct xinpgen *)buf;
        exig = (struct xinpgen *)(void *)((char *)buf + len - sizeof *exig);
        if (xig->xig_len != sizeof *xig || exig->xig_len != sizeof *exig) {
            PyErr_Format(PyExc_RuntimeError, "struct xinpgen size mismatch");
            goto error;
        }
    } while (xig->xig_gen != exig->xig_gen && retry--);

    for (;;) {
        int lport, rport, pid, status, family;

        xig = (struct xinpgen *)(void *)((char *)xig + xig->xig_len);
        if (xig >= exig)
            break;

        switch (proto) {
            case IPPROTO_TCP:
                xtp = (struct xtcpcb *)xig;
                if (xtp->xt_len != sizeof *xtp) {
                    PyErr_Format(PyExc_RuntimeError,
                                 "struct xtcpcb size mismatch");
                    goto error;
                }
                inp = &xtp->xt_inp;
                so = &xtp->xt_socket;
                status = xtp->xt_tp.t_state;
                break;
            case IPPROTO_UDP:
                xip = (struct xinpcb *)xig;
                if (xip->xi_len != sizeof *xip) {
                    PyErr_Format(PyExc_RuntimeError,
                                 "struct xinpcb size mismatch");
                    goto error;
                }
                inp = &xip->xi_inp;
                so = &xip->xi_socket;
                status = PSUTIL_CONN_NONE;
                break;
            default:
                PyErr_Format(PyExc_RuntimeError, "invalid proto");
                goto error;
        }

        char lip[200], rip[200];

        hash = (int)((uintptr_t)so->xso_so % HASHSIZE);
        pid = psutil_get_pid_from_sock(hash);
        if (pid < 0)
            continue;
        lport = ntohs(inp->inp_lport);
        rport = ntohs(inp->inp_fport);

        if (inp->inp_vflag & INP_IPV4) {
            family = AF_INET;
            inet_ntop(AF_INET, &inp->inp_laddr.s_addr, lip, sizeof(lip));
            inet_ntop(AF_INET, &inp->inp_faddr.s_addr, rip, sizeof(rip));
        }
        else if (inp->inp_vflag & INP_IPV6) {
            family = AF_INET6;
            inet_ntop(AF_INET6, &inp->in6p_laddr.s6_addr, lip, sizeof(lip));
            inet_ntop(AF_INET6, &inp->in6p_faddr.s6_addr, rip, sizeof(rip));
        }

        // construct python tuple/list
        py_laddr = Py_BuildValue("(si)", lip, lport);
        if (!py_laddr)
            goto error;
        if (rport != 0)
            py_raddr = Py_BuildValue("(si)", rip, rport);
        else
            py_raddr = Py_BuildValue("()");
        if (!py_raddr)
            goto error;
        py_tuple = Py_BuildValue("(iiiNNii)", -1, family, type, py_laddr,
                                 py_raddr, status, pid);
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }

    free(buf);
    return 1;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_laddr);
    Py_XDECREF(py_raddr);
    free(buf);
    return 0;
}


int psutil_gather_unix(int proto, PyObject *py_retlist) {
    struct xunpgen *xug, *exug;
    struct xunpcb *xup;
    const char *varname = NULL;
    const char *protoname = NULL;
    size_t len;
    size_t bufsize;
    void *buf;
    int hash;
    int retry;
    int pid;
    struct sockaddr_un *sun;
    char path[PATH_MAX];

    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;

    switch (proto) {
        case SOCK_STREAM:
            varname = "net.local.stream.pcblist";
            protoname = "stream";
            break;
        case SOCK_DGRAM:
            varname = "net.local.dgram.pcblist";
            protoname = "dgram";
            break;
    }

    buf = NULL;
    bufsize = 8192;
    retry = 5;

    do {
        for (;;) {
            buf = realloc(buf, bufsize);
            if (buf == NULL) {
                PyErr_NoMemory();
                goto error;
            }
            len = bufsize;
            if (sysctlbyname(varname, buf, &len, NULL, 0) == 0)
                break;
            if (errno != ENOMEM) {
                PyErr_SetFromErrno(0);
                goto error;
            }
            bufsize *= 2;
        }
        xug = (struct xunpgen *)buf;
        exug = (struct xunpgen *)(void *)
            ((char *)buf + len - sizeof *exug);
        if (xug->xug_len != sizeof *xug || exug->xug_len != sizeof *exug) {
            PyErr_Format(PyExc_RuntimeError, "struct xinpgen size mismatch");
            goto error;
        }
    } while (xug->xug_gen != exug->xug_gen && retry--);

    for (;;) {
        xug = (struct xunpgen *)(void *)((char *)xug + xug->xug_len);
        if (xug >= exug)
            break;
        xup = (struct xunpcb *)xug;
        if (xup->xu_len != sizeof *xup)
            goto error;

        hash = (int)((uintptr_t) xup->xu_socket.xso_so % HASHSIZE);
        pid = psutil_get_pid_from_sock(hash);
        if (pid < 0)
            continue;

        sun = (struct sockaddr_un *)&xup->xu_addr;
        snprintf(path, sizeof(path), "%.*s",
                 (int)(sun->sun_len - (sizeof(*sun) - sizeof(sun->sun_path))),
                 sun->sun_path);

        py_tuple = Py_BuildValue("(iiisOii)", -1, AF_UNIX, proto, path,
                                 Py_None, PSUTIL_CONN_NONE, pid);
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
        Py_INCREF(Py_None);
    }

    free(buf);
    return 1;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_laddr);
    Py_XDECREF(py_raddr);
    free(buf);
    return 0;
}


PyObject*
psutil_net_connections(PyObject* self, PyObject* args) {
    // Return system-wide open connections.
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;
    if (psutil_populate_xfiles() != 1)
        goto error;
    if (psutil_gather_inet(IPPROTO_TCP, py_retlist) == 0)
        goto error;
    if (psutil_gather_inet(IPPROTO_UDP, py_retlist) == 0)
        goto error;
    if (psutil_gather_unix(SOCK_STREAM, py_retlist) == 0)
       goto error;
    if (psutil_gather_unix(SOCK_DGRAM, py_retlist) == 0)
        goto error;

    free(psutil_xfiles);
    return py_retlist;

error:
    Py_DECREF(py_retlist);
    free(psutil_xfiles);
    return NULL;
}


PyObject *
psutil_proc_connections(PyObject *self, PyObject *args) {
    // Return connections opened by process.
    long pid;
    int i, cnt;
    struct kinfo_file *freep = NULL;
    struct kinfo_file *kif;
    char *tcplist = NULL;
    struct tcpcb *tcp;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;
    PyObject *py_af_filter = NULL;
    PyObject *py_type_filter = NULL;
    PyObject *py_family = NULL;
    PyObject *py_type = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "lOO", &pid, &py_af_filter, &py_type_filter))
        goto error;
    if (!PySequence_Check(py_af_filter) || !PySequence_Check(py_type_filter)) {
        PyErr_SetString(PyExc_TypeError, "arg 2 or 3 is not a sequence");
        goto error;
    }

    errno = 0;
    freep = kinfo_getfile(pid, &cnt);
    if (freep == NULL) {
        psutil_raise_for_pid(pid, "kinfo_getfile() failed");
        goto error;
    }

    tcplist = psutil_fetch_tcplist();
    if (tcplist == NULL) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (i = 0; i < cnt; i++) {
        int lport, rport, state;
        char lip[200], rip[200];
        char path[PATH_MAX];
        int inseq;
        py_tuple = NULL;
        py_laddr = NULL;
        py_raddr = NULL;

        kif = &freep[i];
        if (kif->kf_type == KF_TYPE_SOCKET) {
            // apply filters
            py_family = PyLong_FromLong((long)kif->kf_sock_domain);
            inseq = PySequence_Contains(py_af_filter, py_family);
            Py_DECREF(py_family);
            if (inseq == 0)
                continue;
            py_type = PyLong_FromLong((long)kif->kf_sock_type);
            inseq = PySequence_Contains(py_type_filter, py_type);
            Py_DECREF(py_type);
            if (inseq == 0)
                continue;
            // IPv4 / IPv6 socket
            if ((kif->kf_sock_domain == AF_INET) ||
                    (kif->kf_sock_domain == AF_INET6)) {
                // fill status
                state = PSUTIL_CONN_NONE;
                if (kif->kf_sock_type == SOCK_STREAM) {
                    tcp = psutil_search_tcplist(tcplist, kif);
                    if (tcp != NULL)
                        state = (int)tcp->t_state;
                }

                // build addr and port
                inet_ntop(
                    kif->kf_sock_domain,
                    psutil_sockaddr_addr(kif->kf_sock_domain,
                                         &kif->kf_sa_local),
                    lip,
                    sizeof(lip));
                inet_ntop(
                    kif->kf_sock_domain,
                    psutil_sockaddr_addr(kif->kf_sock_domain,
                                         &kif->kf_sa_peer),
                    rip,
                    sizeof(rip));
                lport = htons(psutil_sockaddr_port(kif->kf_sock_domain,
                                                   &kif->kf_sa_local));
                rport = htons(psutil_sockaddr_port(kif->kf_sock_domain,
                                                   &kif->kf_sa_peer));

                // construct python tuple/list
                py_laddr = Py_BuildValue("(si)", lip, lport);
                if (!py_laddr)
                    goto error;
                if (rport != 0)
                    py_raddr = Py_BuildValue("(si)", rip, rport);
                else
                    py_raddr = Py_BuildValue("()");
                if (!py_raddr)
                    goto error;
                py_tuple = Py_BuildValue(
                    "(iiiNNi)",
                    kif->kf_fd,
                    kif->kf_sock_domain,
                    kif->kf_sock_type,
                    py_laddr,
                    py_raddr,
                    state
                );
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
            // UNIX socket
            else if (kif->kf_sock_domain == AF_UNIX) {
                struct sockaddr_un *sun;

                sun = (struct sockaddr_un *)&kif->kf_sa_local;
                snprintf(
                    path, sizeof(path), "%.*s",
                    (int)(sun->sun_len - (sizeof(*sun) - sizeof(sun->sun_path))),
                    sun->sun_path);

                py_tuple = Py_BuildValue(
                    "(iiisOi)",
                    kif->kf_fd,
                    kif->kf_sock_domain,
                    kif->kf_sock_type,
                    path,
                    Py_None,
                    PSUTIL_CONN_NONE
                );
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
                Py_INCREF(Py_None);
            }
        }
    }
    free(freep);
    free(tcplist);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_laddr);
    Py_XDECREF(py_raddr);
    Py_DECREF(py_retlist);
    if (freep != NULL)
        free(freep);
    if (tcplist != NULL)
        free(tcplist);
    return NULL;
}
