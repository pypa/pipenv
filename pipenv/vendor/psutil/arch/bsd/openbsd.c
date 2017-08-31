/*
 * Copyright (c) 2009, Giampaolo Rodola', Landry Breuil.
 * All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Platform-specific module methods for OpenBSD.
 */

#include <Python.h>
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/param.h>
#include <sys/sysctl.h>
#include <sys/user.h>
#include <sys/proc.h>
#include <sys/mount.h>  // for VFS_*
#include <sys/swap.h>  // for swap_mem
#include <sys/vmmeter.h>  // for vmtotal struct
#include <signal.h>
#include <kvm.h>
// connection stuff
#include <netdb.h>  // for NI_MAXHOST
#include <sys/socket.h>
#include <sys/sched.h>  // for CPUSTATES & CP_*
#define _KERNEL  // for DTYPE_*
#include <sys/file.h>
#undef _KERNEL
#include <sys/disk.h>  // struct diskstats
#include <arpa/inet.h> // for inet_ntoa()
#include <err.h> // for warn() & err()


#include "../../_psutil_common.h"

#define PSUTIL_KPT2DOUBLE(t) (t ## _sec + t ## _usec / 1000000.0)
// #define PSUTIL_TV2DOUBLE(t) ((t).tv_sec + (t).tv_usec / 1000000.0)

// a signaler for connections without an actual status
int PSUTIL_CONN_NONE = 128;


// ============================================================================
// Utility functions
// ============================================================================

int
psutil_kinfo_proc(pid_t pid, struct kinfo_proc *proc) {
    // Fills a kinfo_proc struct based on process pid.
    int ret;
    int mib[6];
    size_t size = sizeof(struct kinfo_proc);

    mib[0] = CTL_KERN;
    mib[1] = KERN_PROC;
    mib[2] = KERN_PROC_PID;
    mib[3] = pid;
    mib[4] = size;
    mib[5] = 1;

    ret = sysctl((int*)mib, 6, proc, &size, NULL, 0);
    if (ret == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }
    // sysctl stores 0 in the size if we can't find the process information.
    if (size == 0) {
        NoSuchProcess();
        return -1;
    }
    return 0;
}


struct kinfo_file *
kinfo_getfile(long pid, int* cnt) {
    // Mimic's FreeBSD kinfo_file call, taking a pid and a ptr to an
    // int as arg and returns an array with cnt struct kinfo_file.
    int mib[6];
    size_t len;
    struct kinfo_file* kf;
    mib[0] = CTL_KERN;
    mib[1] = KERN_FILE;
    mib[2] = KERN_FILE_BYPID;
    mib[3] = (int) pid;
    mib[4] = sizeof(struct kinfo_file);
    mib[5] = 0;

    /* get the size of what would be returned */
    if (sysctl(mib, 6, NULL, &len, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }
    if ((kf = malloc(len)) == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    mib[5] = (int)(len / sizeof(struct kinfo_file));
    if (sysctl(mib, 6, kf, &len, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    *cnt = (int)(len / sizeof(struct kinfo_file));
    return kf;
}


// ============================================================================
// APIS
// ============================================================================

int
psutil_get_proc_list(struct kinfo_proc **procList, size_t *procCount) {
    // Returns a list of all BSD processes on the system.  This routine
    // allocates the list and puts it in *procList and a count of the
    // number of entries in *procCount.  You are responsible for freeing
    // this list (use "free" from System framework).
    // On success, the function returns 0.
    // On error, the function returns a BSD errno value.
    struct kinfo_proc *result;
    // Declaring name as const requires us to cast it when passing it to
    // sysctl because the prototype doesn't include the const modifier.
    char errbuf[_POSIX2_LINE_MAX];
    int cnt;
    kvm_t *kd;

    assert(procList != NULL);
    assert(*procList == NULL);
    assert(procCount != NULL);

    kd = kvm_openfiles(NULL, NULL, NULL, KVM_NO_FILES, errbuf);

    if (kd == NULL) {
        return errno;
    }

    result = kvm_getprocs(kd, KERN_PROC_ALL, 0, sizeof(struct kinfo_proc), &cnt);
    if (result == NULL) {
        kvm_close(kd);
        err(1, NULL);
        return errno;
    }

    *procCount = (size_t)cnt;

    size_t mlen = cnt * sizeof(struct kinfo_proc);

    if ((*procList = malloc(mlen)) == NULL) {
        kvm_close(kd);
        err(1, NULL);
        return errno;
    }

    memcpy(*procList, result, mlen);
    assert(*procList != NULL);
    kvm_close(kd);

    return 0;
}


char **
_psutil_get_argv(long pid) {
    static char **argv;
    int argv_mib[] = {CTL_KERN, KERN_PROC_ARGS, pid, KERN_PROC_ARGV};
    size_t argv_size = 128;
    /* Loop and reallocate until we have enough space to fit argv. */
    for (;; argv_size *= 2) {
        if ((argv = realloc(argv, argv_size)) == NULL)
            err(1, NULL);
        if (sysctl(argv_mib, 4, argv, &argv_size, NULL, 0) == 0)
            return argv;
        if (errno == ESRCH) {
            PyErr_SetFromErrno(PyExc_OSError);
            return NULL;
        }
        if (errno != ENOMEM)
            err(1, NULL);
    }
}


// returns the command line as a python list object
PyObject *
psutil_get_cmdline(long pid) {
    static char **argv;
    char **p;
    PyObject *py_arg = NULL;
    PyObject *py_retlist = Py_BuildValue("[]");

    if (!py_retlist)
        return NULL;
    if (pid < 0)
        return py_retlist;

    if ((argv = _psutil_get_argv(pid)) == NULL)
        goto error;

    for (p = argv; *p != NULL; p++) {
#if PY_MAJOR_VERSION >= 3
        py_arg = PyUnicode_DecodeFSDefault(*p);
#else
        py_arg = Py_BuildValue("s", *p);
#endif
        if (!py_arg)
            goto error;
        if (PyList_Append(py_retlist, py_arg))
            goto error;
        Py_DECREF(py_arg);
    }
    return py_retlist;

error:
    Py_XDECREF(py_arg);
    Py_DECREF(py_retlist);
    return NULL;
}


PyObject *
psutil_proc_threads(PyObject *self, PyObject *args) {
    // OpenBSD reference:
    // https://github.com/janmojzis/pstree/blob/master/proc_kvm.c
    // Note: this requires root access, else it will fail trying
    // to access /dev/kmem.
    long pid;
    kvm_t *kd = NULL;
    int nentries, i;
    char errbuf[4096];
    struct kinfo_proc *kp;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;

    kd = kvm_openfiles(0, 0, 0, O_RDONLY, errbuf);
    if (! kd) {
        if (strstr(errbuf, "Permission denied") != NULL)
            AccessDenied();
        else
            PyErr_Format(PyExc_RuntimeError, "kvm_openfiles() syscall failed");
        goto error;
    }

    kp = kvm_getprocs(
        kd, KERN_PROC_PID | KERN_PROC_SHOW_THREADS | KERN_PROC_KTHREAD, pid,
        sizeof(*kp), &nentries);
    if (! kp) {
        if (strstr(errbuf, "Permission denied") != NULL)
            AccessDenied();
        else
            PyErr_Format(PyExc_RuntimeError, "kvm_getprocs() syscall failed");
        goto error;
    }

    for (i = 0; i < nentries; i++) {
        if (kp[i].p_tid < 0)
            continue;
        if (kp[i].p_pid == pid) {
            py_tuple = Py_BuildValue(
                "Idd",
                kp[i].p_tid,
                PSUTIL_KPT2DOUBLE(kp[i].p_uutime),
                PSUTIL_KPT2DOUBLE(kp[i].p_ustime));
            if (py_tuple == NULL)
                goto error;
            if (PyList_Append(py_retlist, py_tuple))
                goto error;
            Py_DECREF(py_tuple);
        }
    }

    kvm_close(kd);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (kd != NULL)
        kvm_close(kd);
    return NULL;
}


PyObject *
psutil_virtual_mem(PyObject *self, PyObject *args) {
    int64_t total_physmem;
    int uvmexp_mib[] = {CTL_VM, VM_UVMEXP};
    int bcstats_mib[] = {CTL_VFS, VFS_GENERIC, VFS_BCACHESTAT};
    int physmem_mib[] = {CTL_HW, HW_PHYSMEM64};
    int vmmeter_mib[] = {CTL_VM, VM_METER};
    size_t size;
    struct uvmexp uvmexp;
    struct bcachestats bcstats;
    struct vmtotal vmdata;
    long pagesize = getpagesize();

    size = sizeof(total_physmem);
    if (sysctl(physmem_mib, 2, &total_physmem, &size, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    size = sizeof(uvmexp);
    if (sysctl(uvmexp_mib, 2, &uvmexp, &size, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    size = sizeof(bcstats);
    if (sysctl(bcstats_mib, 3, &bcstats, &size, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    size = sizeof(vmdata);
    if (sysctl(vmmeter_mib, 2, &vmdata, &size, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    return Py_BuildValue("KKKKKKKK",
        // Note: many programs calculate total memory as
        // "uvmexp.npages * pagesize" but this is incorrect and does not
        // match "sysctl | grep hw.physmem".
        (unsigned long long) total_physmem,
        (unsigned long long) uvmexp.free * pagesize,
        (unsigned long long) uvmexp.active * pagesize,
        (unsigned long long) uvmexp.inactive * pagesize,
        (unsigned long long) uvmexp.wired * pagesize,
        // this is how "top" determines it
        (unsigned long long) bcstats.numbufpages * pagesize,  // cached
        (unsigned long long) 0,  // buffers
        (unsigned long long) vmdata.t_vmshr + vmdata.t_rmshr  // shared
    );
}


PyObject *
psutil_swap_mem(PyObject *self, PyObject *args) {
    uint64_t swap_total, swap_free;
    struct swapent *swdev;
    int nswap, i;

    if ((nswap = swapctl(SWAP_NSWAP, 0, 0)) == 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    if ((swdev = calloc(nswap, sizeof(*swdev))) == NULL) {
        PyErr_NoMemory();
        return NULL;
    }

    if (swapctl(SWAP_STATS, swdev, nswap) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    // Total things up.
    swap_total = swap_free = 0;
    for (i = 0; i < nswap; i++) {
        if (swdev[i].se_flags & SWF_ENABLE) {
            swap_free += (swdev[i].se_nblks - swdev[i].se_inuse);
            swap_total += swdev[i].se_nblks;
        }
    }

    free(swdev);
    return Py_BuildValue("(LLLII)",
                         swap_total * DEV_BSIZE,
                         (swap_total - swap_free) * DEV_BSIZE,
                         swap_free * DEV_BSIZE,
                         // swap in / swap out is not supported as the
                         // swapent struct does not provide any info
                         // about it.
                         0, 0);

error:
    free(swdev);
    return NULL;
}


PyObject *
psutil_proc_num_fds(PyObject *self, PyObject *args) {
    long pid;
    int cnt;

    struct kinfo_file *freep;
    struct kinfo_proc kipp;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (psutil_kinfo_proc(pid, &kipp) == -1)
        return NULL;

    errno = 0;
    freep = kinfo_getfile(pid, &cnt);
    if (freep == NULL) {
        psutil_raise_for_pid(pid, "kinfo_getfile() failed");
        return NULL;
    }
    free(freep);

    return Py_BuildValue("i", cnt);
}


PyObject *
psutil_proc_cwd(PyObject *self, PyObject *args) {
    // Reference:
    // http://anoncvs.spacehopper.org/openbsd-src/tree/bin/ps/print.c#n179
    long pid;
    struct kinfo_proc kp;
    char path[MAXPATHLEN];
    size_t pathlen = sizeof path;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (psutil_kinfo_proc(pid, &kp) == -1)
        return NULL;

    int name[] = { CTL_KERN, KERN_PROC_CWD, pid };
    if (sysctl(name, 3, path, &pathlen, NULL, 0) != 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }
#if PY_MAJOR_VERSION >= 3
    return PyUnicode_DecodeFSDefault(path);
#else
    return Py_BuildValue("s", path);
#endif
}


// see sys/kern/kern_sysctl.c lines 1100 and
// usr.bin/fstat/fstat.c print_inet_details()
static char *
psutil_convert_ipv4(int family, uint32_t addr[4]) {
    struct in_addr a;
    memcpy(&a, addr, sizeof(a));
    return inet_ntoa(a);
}


static char *
psutil_inet6_addrstr(struct in6_addr *p)
{
    struct sockaddr_in6 sin6;
    static char hbuf[NI_MAXHOST];
    const int niflags = NI_NUMERICHOST;

    memset(&sin6, 0, sizeof(sin6));
    sin6.sin6_family = AF_INET6;
    sin6.sin6_len = sizeof(struct sockaddr_in6);
    sin6.sin6_addr = *p;
    if (IN6_IS_ADDR_LINKLOCAL(p) &&
        *(u_int16_t *)&sin6.sin6_addr.s6_addr[2] != 0) {
        sin6.sin6_scope_id =
            ntohs(*(u_int16_t *)&sin6.sin6_addr.s6_addr[2]);
        sin6.sin6_addr.s6_addr[2] = sin6.sin6_addr.s6_addr[3] = 0;
    }

    if (getnameinfo((struct sockaddr *)&sin6, sin6.sin6_len,
        hbuf, sizeof(hbuf), NULL, 0, niflags))
        return "invalid";

    return hbuf;
}


PyObject *
psutil_proc_connections(PyObject *self, PyObject *args) {
    long pid;
    int i, cnt;

    struct kinfo_file *freep = NULL;
    struct kinfo_file *kif;
    char *tcplist = NULL;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;
    PyObject *py_af_filter = NULL;
    PyObject *py_type_filter = NULL;
    PyObject *py_family = NULL;
    PyObject *_type = NULL;

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

    for (i = 0; i < cnt; i++) {
        int state;
        int lport;
        int rport;
        char addrbuf[NI_MAXHOST + 2];
        int inseq;
        struct in6_addr laddr6;
        py_tuple = NULL;
        py_laddr = NULL;
        py_raddr = NULL;

        kif = &freep[i];
        if (kif->f_type == DTYPE_SOCKET) {
            // apply filters
            py_family = PyLong_FromLong((long)kif->so_family);
            inseq = PySequence_Contains(py_af_filter, py_family);
            Py_DECREF(py_family);
            if (inseq == 0)
                continue;
            _type = PyLong_FromLong((long)kif->so_type);
            inseq = PySequence_Contains(py_type_filter, _type);
            Py_DECREF(_type);
            if (inseq == 0)
                continue;

            // IPv4 / IPv6 socket
            if ((kif->so_family == AF_INET) || (kif->so_family == AF_INET6)) {
                // fill status
                if (kif->so_type == SOCK_STREAM)
                    state = kif->t_state;
                else
                    state = PSUTIL_CONN_NONE;

                // ports
                lport = ntohs(kif->inp_lport);
                rport = ntohs(kif->inp_fport);

                // local address, IPv4
                if (kif->so_family == AF_INET) {
                    py_laddr = Py_BuildValue(
                        "(si)",
                        psutil_convert_ipv4(kif->so_family, kif->inp_laddru),
                        lport);
                    if (!py_laddr)
                        goto error;
                }
                else {
                    // local address, IPv6
                    memcpy(&laddr6, kif->inp_laddru, sizeof(laddr6));
                    snprintf(addrbuf, sizeof(addrbuf), "%s",
                             psutil_inet6_addrstr(&laddr6));
                    py_laddr = Py_BuildValue("(si)", addrbuf, lport);
                    if (!py_laddr)
                        goto error;
                }

                if (rport != 0) {
                    // remote address, IPv4
                    if (kif->so_family == AF_INET) {
                        py_raddr = Py_BuildValue(
                            "(si)",
                            psutil_convert_ipv4(
                                kif->so_family, kif->inp_faddru),
                            rport);
                    }
                    else {
                        // remote address, IPv6
                        memcpy(&laddr6, kif->inp_faddru, sizeof(laddr6));
                        snprintf(addrbuf, sizeof(addrbuf), "%s",
                                 psutil_inet6_addrstr(&laddr6));
                        py_raddr = Py_BuildValue("(si)", addrbuf, rport);
                        if (!py_raddr)
                            goto error;
                    }
                }
                else {
                    py_raddr = Py_BuildValue("()");
                }

                if (!py_raddr)
                    goto error;
                py_tuple = Py_BuildValue(
                    "(iiiNNi)",
                    kif->fd_fd,
                    kif->so_family,
                    kif->so_type,
                    py_laddr,
                    py_raddr,
                    state);
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
            // UNIX socket
            else if (kif->so_family == AF_UNIX) {
                py_tuple = Py_BuildValue(
                    "(iiisOi)",
                    kif->fd_fd,
                    kif->so_family,
                    kif->so_type,
                    kif->unp_path,
                    Py_None,
                    PSUTIL_CONN_NONE);
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


PyObject *
psutil_per_cpu_times(PyObject *self, PyObject *args) {
    int mib[3];
    int ncpu;
    size_t len;
    size_t size;
    int i;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_cputime = NULL;

    if (py_retlist == NULL)
        return NULL;


    // retrieve the number of cpus
    mib[0] = CTL_HW;
    mib[1] = HW_NCPU;
    len = sizeof(ncpu);
    if (sysctl(mib, 2, &ncpu, &len, NULL, 0) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    uint64_t cpu_time[CPUSTATES];

    for (i = 0; i < ncpu; i++) {
        // per-cpu info
        mib[0] = CTL_KERN;
        mib[1] = KERN_CPTIME2;
        mib[2] = i;
        size = sizeof(cpu_time);
        if (sysctl(mib, 3, &cpu_time, &size, NULL, 0) == -1) {
            warn("failed to get kern.cptime2");
            PyErr_SetFromErrno(PyExc_OSError);
            return NULL;
        }

        py_cputime = Py_BuildValue(
            "(ddddd)",
            (double)cpu_time[CP_USER] / CLOCKS_PER_SEC,
            (double)cpu_time[CP_NICE] / CLOCKS_PER_SEC,
            (double)cpu_time[CP_SYS] / CLOCKS_PER_SEC,
            (double)cpu_time[CP_IDLE] / CLOCKS_PER_SEC,
            (double)cpu_time[CP_INTR] / CLOCKS_PER_SEC);
        if (!py_cputime)
            goto error;
        if (PyList_Append(py_retlist, py_cputime))
            goto error;
        Py_DECREF(py_cputime);
    }

    return py_retlist;

error:
    Py_XDECREF(py_cputime);
    Py_DECREF(py_retlist);
    return NULL;
}


PyObject *
psutil_disk_io_counters(PyObject *self, PyObject *args) {
    int i, dk_ndrive, mib[3];
    size_t len;
    struct diskstats *stats;

    PyObject *py_retdict = PyDict_New();
    PyObject *py_disk_info = NULL;
    if (py_retdict == NULL)
        return NULL;

    mib[0] = CTL_HW;
    mib[1] = HW_DISKSTATS;
    len = 0;
    if (sysctl(mib, 2, NULL, &len, NULL, 0) < 0) {
        warn("can't get hw.diskstats size");
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    dk_ndrive = (int)(len / sizeof(struct diskstats));

    stats = malloc(len);
    if (stats == NULL) {
        warn("can't malloc");
        PyErr_NoMemory();
        goto error;
    }
    if (sysctl(mib, 2, stats, &len, NULL, 0) < 0 ) {
        warn("could not read hw.diskstats");
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (i = 0; i < dk_ndrive; i++) {
        py_disk_info = Py_BuildValue(
            "(KKKK)",
            stats[i].ds_rxfer,  // num reads
            stats[i].ds_wxfer,  // num writes
            stats[i].ds_rbytes,  // read bytes
            stats[i].ds_wbytes  // write bytes
        );
        if (!py_disk_info)
            goto error;
        if (PyDict_SetItemString(py_retdict, stats[i].ds_name, py_disk_info))
            goto error;
        Py_DECREF(py_disk_info);
    }

    free(stats);
    return py_retdict;

error:
    Py_XDECREF(py_disk_info);
    Py_DECREF(py_retdict);
    if (stats != NULL)
        free(stats);
    return NULL;
}


PyObject *
psutil_cpu_stats(PyObject *self, PyObject *args) {
    size_t size;
    struct uvmexp uv;
    int uvmexp_mib[] = {CTL_VM, VM_UVMEXP};

    size = sizeof(uv);
    if (sysctl(uvmexp_mib, 2, &uv, &size, NULL, 0) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    return Py_BuildValue(
        "IIIIIII",
        uv.swtch,  // ctx switches
        uv.intrs,  // interrupts - XXX always 0, will be determined via /proc
        uv.softs,  // soft interrupts
        uv.syscalls,  // syscalls - XXX always 0
        uv.traps,  // traps
        uv.faults,  // faults
        uv.forks  // forks
    );
}
