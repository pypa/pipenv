/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Functions specific to Sun OS Solaris platforms.
 *
 * Thanks to Justin Venus who originally wrote a consistent part of
 * this in Cython which I later on translated in C.
 */


#include <Python.h>

// fix for "Cannot use procfs in the large file compilation environment"
// error, see:
// http://sourceware.org/ml/gdb-patches/2010-11/msg00336.html
#undef _FILE_OFFSET_BITS
#define _STRUCTURED_PROC 1

// fix compilation issue on SunOS 5.10, see:
// https://github.com/giampaolo/psutil/issues/421
#define NEW_MIB_COMPLIANT

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/proc.h>
#include <sys/swap.h>
#include <sys/sysinfo.h>
#include <sys/mntent.h>  // for MNTTAB
#include <sys/mnttab.h>
#include <sys/procfs.h>
#include <sys/sockio.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <utmpx.h>
#include <kstat.h>
#include <sys/ioctl.h>
#include <sys/tihdr.h>
#include <stropts.h>
#include <inet/tcp.h>
#include <arpa/inet.h>
#include <net/if.h>


#define PSUTIL_TV2DOUBLE(t) (((t).tv_nsec * 0.000000001) + (t).tv_sec)
#ifndef EXPER_IP_AND_ALL_IRES
#define EXPER_IP_AND_ALL_IRES (1024+4)
#endif
// a signaler for connections without an actual status
static int PSUTIL_CONN_NONE = 128;


/*
 * Read a file content and fills a C structure with it.
 */
int
psutil_file_to_struct(char *path, void *fstruct, size_t size) {
    int fd;
    size_t nbytes;
    fd = open(path, O_RDONLY);
    if (fd == -1) {
        PyErr_SetFromErrnoWithFilename(PyExc_OSError, path);
        return 0;
    }
    nbytes = read(fd, fstruct, size);
    if (nbytes == -1) {
        close(fd);
        PyErr_SetFromErrno(PyExc_OSError);
        return 0;
    }
    if (nbytes != size) {
        close(fd);
        PyErr_SetString(
            PyExc_RuntimeError, "read() file structure size mismatch");
        return 0;
    }
    close(fd);
    return nbytes;
}


/*
 * Return process ppid, rss, vms, ctime, nice, nthreads, status and tty
 * as a Python tuple.
 */
static PyObject *
psutil_proc_basic_info(PyObject *self, PyObject *args) {
    int pid;
    char path[1000];
    psinfo_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;

    sprintf(path, "%s/%i/psinfo", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;
    return Py_BuildValue("ikkdiiik",
                         info.pr_ppid,              // parent pid
                         info.pr_rssize,            // rss
                         info.pr_size,              // vms
                         PSUTIL_TV2DOUBLE(info.pr_start),  // create time
                         info.pr_lwp.pr_nice,       // nice
                         info.pr_nlwp,              // no. of threads
                         info.pr_lwp.pr_state,      // status code
                         info.pr_ttydev             // tty nr
                        );
}


/*
 * Return process name and args as a Python tuple.
 */
static PyObject *
psutil_proc_name_and_args(PyObject *self, PyObject *args) {
    int pid;
    char path[1000];
    psinfo_t info;
    const char *procfs_path;
    PyObject *py_name;
    PyObject *py_args;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/psinfo", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;

#if PY_MAJOR_VERSION >= 3
    py_name = PyUnicode_DecodeFSDefault(info.pr_fname);
    if (!py_name)
        return NULL;
    py_args = PyUnicode_DecodeFSDefault(info.pr_psargs);
    if (!py_args)
        return NULL;
    return Py_BuildValue("OO", py_name, py_args);
#else
    return Py_BuildValue("ss", info.pr_fname, info.pr_psargs);
#endif
}


/*
 * Return process user and system CPU times as a Python tuple.
 */
static PyObject *
psutil_proc_cpu_times(PyObject *self, PyObject *args) {
    int pid;
    char path[1000];
    pstatus_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/status", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;
    // results are more precise than os.times()
    return Py_BuildValue(
        "(dddd)",
         PSUTIL_TV2DOUBLE(info.pr_utime),
         PSUTIL_TV2DOUBLE(info.pr_stime),
         PSUTIL_TV2DOUBLE(info.pr_cutime),
         PSUTIL_TV2DOUBLE(info.pr_cstime)
    );
}


/*
 * Return what CPU the process is running on.
 */
static PyObject *
psutil_proc_cpu_num(PyObject *self, PyObject *args) {
    int fd = NULL;
    int pid;
    char path[1000];
    struct prheader header;
    struct lwpsinfo *lwp;
    char *lpsinfo = NULL;
    char *ptr = NULL;
    int nent;
    int size;
    int proc_num;
    size_t nbytes;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;

    sprintf(path, "%s/%i/lpsinfo", procfs_path, pid);
    fd = open(path, O_RDONLY);
    if (fd == -1) {
        PyErr_SetFromErrnoWithFilename(PyExc_OSError, path);
        return NULL;
    }

    // read header
    nbytes = pread(fd, &header, sizeof(header), 0);
    if (nbytes == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    if (nbytes != sizeof(header)) {
        PyErr_SetString(
            PyExc_RuntimeError, "read() file structure size mismatch");
        goto error;
    }

    // malloc
    nent = header.pr_nent;
    size = header.pr_entsize * nent;
    ptr = lpsinfo = malloc(size);
    if (lpsinfo == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    // read the rest
    nbytes = pread(fd, lpsinfo, size, sizeof(header));
    if (nbytes == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    if (nbytes != size) {
        PyErr_SetString(
            PyExc_RuntimeError, "read() file structure size mismatch");
        goto error;
    }

    // done
    lwp = (lwpsinfo_t *)ptr;
    proc_num = lwp->pr_onpro;
    close(fd);
    free(ptr);
    free(lpsinfo);
    return Py_BuildValue("i", proc_num);

error:
    if (fd != NULL)
        close(fd);
    if (ptr != NULL)
        free(ptr);
    if (lpsinfo != NULL)
        free(lpsinfo);
    return NULL;
}


/*
 * Return process uids/gids as a Python tuple.
 */
static PyObject *
psutil_proc_cred(PyObject *self, PyObject *args) {
    int pid;
    char path[1000];
    prcred_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/cred", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;
    return Py_BuildValue("iiiiii",
                         info.pr_ruid, info.pr_euid, info.pr_suid,
                         info.pr_rgid, info.pr_egid, info.pr_sgid);
}


/*
 * Return process uids/gids as a Python tuple.
 */
static PyObject *
psutil_proc_num_ctx_switches(PyObject *self, PyObject *args) {
    int pid;
    char path[1000];
    prusage_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/usage", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;
    return Py_BuildValue("kk", info.pr_vctx, info.pr_ictx);
}


/*
 * Process IO counters.
 *
 * Commented out and left here as a reminder.  Apparently we cannot
 * retrieve process IO stats because:
 * - 'pr_ioch' is a sum of chars read and written, with no distinction
 * - 'pr_inblk' and 'pr_oublk', which should be the number of bytes
 *    read and written, hardly increase and according to:
 *    http://www.brendangregg.com/Perf/paper_diskubyp1.pdf
 *    ...they should be meaningless anyway.
 *
static PyObject*
proc_io_counters(PyObject* self, PyObject* args) {
    int pid;
    char path[1000];
    prusage_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/usage", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;

    // On Solaris we only have 'pr_ioch' which accounts for bytes read
    // *and* written.
    // 'pr_inblk' and 'pr_oublk' should be expressed in blocks of
    // 8KB according to:
    // http://www.brendangregg.com/Perf/paper_diskubyp1.pdf  (pag. 8)
    return Py_BuildValue("kkkk",
                         info.pr_ioch,
                         info.pr_ioch,
                         info.pr_inblk,
                         info.pr_oublk);
}
 */


/*
 * Return information about a given process thread.
 */
static PyObject *
psutil_proc_query_thread(PyObject *self, PyObject *args) {
    int pid, tid;
    char path[1000];
    lwpstatus_t info;
    const char *procfs_path;

    if (! PyArg_ParseTuple(args, "iis", &pid, &tid, &procfs_path))
        return NULL;
    sprintf(path, "%s/%i/lwp/%i/lwpstatus", procfs_path, pid, tid);
    if (! psutil_file_to_struct(path, (void *)&info, sizeof(info)))
        return NULL;
    return Py_BuildValue("dd",
                         PSUTIL_TV2DOUBLE(info.pr_utime),
                         PSUTIL_TV2DOUBLE(info.pr_stime));
}


/*
 * Return information about system virtual memory.
 */
static PyObject *
psutil_swap_mem(PyObject *self, PyObject *args) {
// XXX (arghhh!)
// total/free swap mem: commented out as for some reason I can't
// manage to get the same results shown by "swap -l", despite the
// code below is exactly the same as:
// http://cvs.opensolaris.org/source/xref/onnv/onnv-gate/usr/src/
//    cmd/swap/swap.c
// We're going to parse "swap -l" output from Python (sigh!)

/*
    struct swaptable     *st;
    struct swapent    *swapent;
    int    i;
    struct stat64 statbuf;
    char *path;
    char fullpath[MAXPATHLEN+1];
    int    num;

    if ((num = swapctl(SC_GETNSWP, NULL)) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }
    if (num == 0) {
        PyErr_SetString(PyExc_RuntimeError, "no swap devices configured");
        return NULL;
    }
    if ((st = malloc(num * sizeof(swapent_t) + sizeof (int))) == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "malloc failed");
        return NULL;
    }
    if ((path = malloc(num * MAXPATHLEN)) == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "malloc failed");
        return NULL;
    }
    swapent = st->swt_ent;
    for (i = 0; i < num; i++, swapent++) {
        swapent->ste_path = path;
        path += MAXPATHLEN;
    }
    st->swt_n = num;
    if ((num = swapctl(SC_LIST, st)) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    swapent = st->swt_ent;
    long t = 0, f = 0;
    for (i = 0; i < num; i++, swapent++) {
        int diskblks_per_page =(int)(sysconf(_SC_PAGESIZE) >> DEV_BSHIFT);
        t += (long)swapent->ste_pages;
        f += (long)swapent->ste_free;
    }

    free(st);
    return Py_BuildValue("(kk)", t, f);
*/

    kstat_ctl_t *kc;
    kstat_t     *k;
    cpu_stat_t  *cpu;
    int         cpu_count = 0;
    int         flag = 0;
    uint_t      sin = 0;
    uint_t      sout = 0;

    kc = kstat_open();
    if (kc == NULL)
        return PyErr_SetFromErrno(PyExc_OSError);;

    k = kc->kc_chain;
    while (k != NULL) {
        if ((strncmp(k->ks_name, "cpu_stat", 8) == 0) && \
                (kstat_read(kc, k, NULL) != -1) )
        {
            flag = 1;
            cpu = (cpu_stat_t *) k->ks_data;
            sin += cpu->cpu_vminfo.pgswapin;    // num pages swapped in
            sout += cpu->cpu_vminfo.pgswapout;  // num pages swapped out
        }
        cpu_count += 1;
        k = k->ks_next;
    }
    kstat_close(kc);
    if (!flag) {
        PyErr_SetString(PyExc_RuntimeError, "no swap device was found");
        return NULL;
    }
    return Py_BuildValue("(II)", sin, sout);
}


/*
 * Return users currently connected on the system.
 */
static PyObject *
psutil_users(PyObject *self, PyObject *args) {
    struct utmpx *ut;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_user_proc = NULL;

    if (py_retlist == NULL)
        return NULL;

    while (NULL != (ut = getutxent())) {
        if (ut->ut_type == USER_PROCESS)
            py_user_proc = Py_True;
        else
            py_user_proc = Py_False;
        py_tuple = Py_BuildValue(
            "(sssfO)",
            ut->ut_user,              // username
            ut->ut_line,              // tty
            ut->ut_host,              // hostname
            (float)ut->ut_tv.tv_sec,  // tstamp
            py_user_proc);            // (bool) user process
        if (py_tuple == NULL)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }
    endutent();

    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (ut != NULL)
        endutent();
    return NULL;
}


/*
 * Return disk mounted partitions as a list of tuples including device,
 * mount point and filesystem type.
 */
static PyObject *
psutil_disk_partitions(PyObject *self, PyObject *args) {
    FILE *file;
    struct mnttab mt;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL)
        return NULL;

    file = fopen(MNTTAB, "rb");
    if (file == NULL) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    while (getmntent(file, &mt) == 0) {
        py_tuple = Py_BuildValue(
            "(ssss)",
            mt.mnt_special,   // device
            mt.mnt_mountp,    // mount point
            mt.mnt_fstype,    // fs type
            mt.mnt_mntopts);  // options
        if (py_tuple == NULL)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);

    }
    fclose(file);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (file != NULL)
        fclose(file);
    return NULL;
}


/*
 * Return system-wide CPU times.
 */
static PyObject *
psutil_per_cpu_times(PyObject *self, PyObject *args) {
    kstat_ctl_t *kc;
    kstat_t *ksp;
    cpu_stat_t cs;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_cputime = NULL;

    if (py_retlist == NULL)
        return NULL;

    kc = kstat_open();
    if (kc == NULL) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (ksp = kc->kc_chain; ksp != NULL; ksp = ksp->ks_next) {
        if (strcmp(ksp->ks_module, "cpu_stat") == 0) {
            if (kstat_read(kc, ksp, &cs) == -1) {
                PyErr_SetFromErrno(PyExc_OSError);
                goto error;
            }
            py_cputime = Py_BuildValue("ffff",
                                       (float)cs.cpu_sysinfo.cpu[CPU_USER],
                                       (float)cs.cpu_sysinfo.cpu[CPU_KERNEL],
                                       (float)cs.cpu_sysinfo.cpu[CPU_IDLE],
                                       (float)cs.cpu_sysinfo.cpu[CPU_WAIT]);
            if (py_cputime == NULL)
                goto error;
            if (PyList_Append(py_retlist, py_cputime))
                goto error;
            Py_DECREF(py_cputime);
            py_cputime = NULL;
        }
    }

    kstat_close(kc);
    return py_retlist;

error:
    Py_XDECREF(py_cputime);
    Py_DECREF(py_retlist);
    if (kc != NULL)
        kstat_close(kc);
    return NULL;
}


/*
 * Return disk IO statistics.
 */
static PyObject *
psutil_disk_io_counters(PyObject *self, PyObject *args) {
    kstat_ctl_t *kc;
    kstat_t *ksp;
    kstat_io_t kio;
    PyObject *py_retdict = PyDict_New();
    PyObject *py_disk_info = NULL;

    if (py_retdict == NULL)
        return NULL;
    kc = kstat_open();
    if (kc == NULL) {
        PyErr_SetFromErrno(PyExc_OSError);;
        goto error;
    }
    ksp = kc->kc_chain;
    while (ksp != NULL) {
        if (ksp->ks_type == KSTAT_TYPE_IO) {
            if (strcmp(ksp->ks_class, "disk") == 0) {
                if (kstat_read(kc, ksp, &kio) == -1) {
                    kstat_close(kc);
                    return PyErr_SetFromErrno(PyExc_OSError);;
                }
                py_disk_info = Py_BuildValue(
                    "(IIKKLL)",
                    kio.reads,
                    kio.writes,
                    kio.nread,
                    kio.nwritten,
                    kio.rtime / 1000 / 1000,  // from nano to milli secs
                    kio.wtime / 1000 / 1000   // from nano to milli secs
                );
                if (!py_disk_info)
                    goto error;
                if (PyDict_SetItemString(py_retdict, ksp->ks_name,
                                         py_disk_info))
                    goto error;
                Py_DECREF(py_disk_info);
            }
        }
        ksp = ksp->ks_next;
    }
    kstat_close(kc);

    return py_retdict;

error:
    Py_XDECREF(py_disk_info);
    Py_DECREF(py_retdict);
    if (kc != NULL)
        kstat_close(kc);
    return NULL;
}


/*
 * Return process memory mappings.
 */
static PyObject *
psutil_proc_memory_maps(PyObject *self, PyObject *args) {
    int pid;
    int fd = -1;
    char path[1000];
    char perms[10];
    char *name;
    struct stat st;
    pstatus_t status;

    prxmap_t *xmap = NULL, *p;
    off_t size;
    size_t nread;
    int nmap;
    uintptr_t pr_addr_sz;
    uintptr_t stk_base_sz, brk_base_sz;
    const char *procfs_path;

    PyObject *py_tuple = NULL;
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "is", &pid, &procfs_path))
        goto error;

    sprintf(path, "%s/%i/status", procfs_path, pid);
    if (! psutil_file_to_struct(path, (void *)&status, sizeof(status)))
        goto error;

    sprintf(path, "%s/%i/xmap", procfs_path, pid);
    if (stat(path, &st) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    size = st.st_size;

    fd = open(path, O_RDONLY);
    if (fd == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    xmap = (prxmap_t *)malloc(size);
    if (xmap == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    nread = pread(fd, xmap, size, 0);
    nmap = nread / sizeof(prxmap_t);
    p = xmap;

    while (nmap) {
        nmap -= 1;
        if (p == NULL) {
            p += 1;
            continue;
        }

        perms[0] = '\0';
        pr_addr_sz = p->pr_vaddr + p->pr_size;

        // perms
        sprintf(perms, "%c%c%c%c%c%c", p->pr_mflags & MA_READ ? 'r' : '-',
                p->pr_mflags & MA_WRITE ? 'w' : '-',
                p->pr_mflags & MA_EXEC ? 'x' : '-',
                p->pr_mflags & MA_SHARED ? 's' : '-',
                p->pr_mflags & MA_NORESERVE ? 'R' : '-',
                p->pr_mflags & MA_RESERVED1 ? '*' : ' ');

        // name
        if (strlen(p->pr_mapname) > 0) {
            name = p->pr_mapname;
        }
        else {
            if ((p->pr_mflags & MA_ISM) || (p->pr_mflags & MA_SHM)) {
                name = "[shmid]";
            }
            else {
                stk_base_sz = status.pr_stkbase + status.pr_stksize;
                brk_base_sz = status.pr_brkbase + status.pr_brksize;

                if ((pr_addr_sz > status.pr_stkbase) &&
                        (p->pr_vaddr < stk_base_sz)) {
                    name = "[stack]";
                }
                else if ((p->pr_mflags & MA_ANON) && \
                         (pr_addr_sz > status.pr_brkbase) && \
                         (p->pr_vaddr < brk_base_sz)) {
                    name = "[heap]";
                }
                else {
                    name = "[anon]";
                }
            }
        }

        py_tuple = Py_BuildValue(
            "iisslll",
            p->pr_vaddr,
            pr_addr_sz,
            perms,
            name,
            (long)p->pr_rss * p->pr_pagesize,
            (long)p->pr_anon * p->pr_pagesize,
            (long)p->pr_locked * p->pr_pagesize);
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);

        // increment pointer
        p += 1;
    }

    close(fd);
    free(xmap);
    return py_retlist;

error:
    if (fd != -1)
        close(fd);
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (xmap != NULL)
        free(xmap);
    return NULL;
}


/*
 * Return a list of tuples for network I/O statistics.
 */
static PyObject *
psutil_net_io_counters(PyObject *self, PyObject *args) {
    kstat_ctl_t    *kc = NULL;
    kstat_t *ksp;
    kstat_named_t *rbytes, *wbytes, *rpkts, *wpkts, *ierrs, *oerrs;
    int ret;
    int sock = -1;
    struct lifreq ifr;

    PyObject *py_retdict = PyDict_New();
    PyObject *py_ifc_info = NULL;

    if (py_retdict == NULL)
        return NULL;
    kc = kstat_open();
    if (kc == NULL)
        goto error;

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    ksp = kc->kc_chain;
    while (ksp != NULL) {
        if (ksp->ks_type != KSTAT_TYPE_NAMED)
            goto next;
        if (strcmp(ksp->ks_class, "net") != 0)
            goto next;
        // skip 'lo' (localhost) because it doesn't have the statistics we need
        // and it makes kstat_data_lookup() fail
        if (strcmp(ksp->ks_module, "lo") == 0)
            goto next;

        // check if this is a network interface by sending a ioctl
        strncpy(ifr.lifr_name, ksp->ks_name, sizeof(ifr.lifr_name));
        ret = ioctl(sock, SIOCGLIFFLAGS, &ifr);
        if (ret == -1)
            goto next;

        if (kstat_read(kc, ksp, NULL) == -1) {
            errno = 0;
            goto next;
        }

        rbytes = (kstat_named_t *)kstat_data_lookup(ksp, "rbytes");
        wbytes = (kstat_named_t *)kstat_data_lookup(ksp, "obytes");
        rpkts = (kstat_named_t *)kstat_data_lookup(ksp, "ipackets");
        wpkts = (kstat_named_t *)kstat_data_lookup(ksp, "opackets");
        ierrs = (kstat_named_t *)kstat_data_lookup(ksp, "ierrors");
        oerrs = (kstat_named_t *)kstat_data_lookup(ksp, "oerrors");

        if ((rbytes == NULL) || (wbytes == NULL) || (rpkts == NULL) ||
                (wpkts == NULL) || (ierrs == NULL) || (oerrs == NULL))
        {
            PyErr_SetString(PyExc_RuntimeError, "kstat_data_lookup() failed");
            goto error;
        }

        if (rbytes->data_type == KSTAT_DATA_UINT64)
        {
            py_ifc_info = Py_BuildValue("(KKKKIIii)",
                                        wbytes->value.ui64,
                                        rbytes->value.ui64,
                                        wpkts->value.ui64,
                                        rpkts->value.ui64,
                                        ierrs->value.ui32,
                                        oerrs->value.ui32,
                                        0,  // dropin not supported
                                        0   // dropout not supported
                                       );
        }
        else
        {
            py_ifc_info = Py_BuildValue("(IIIIIIii)",
                                        wbytes->value.ui32,
                                        rbytes->value.ui32,
                                        wpkts->value.ui32,
                                        rpkts->value.ui32,
                                        ierrs->value.ui32,
                                        oerrs->value.ui32,
                                        0,  // dropin not supported
                                        0   // dropout not supported
                                       );
        }
        if (!py_ifc_info)
            goto error;
        if (PyDict_SetItemString(py_retdict, ksp->ks_name, py_ifc_info))
            goto error;
        Py_DECREF(py_ifc_info);
        goto next;

next:
        ksp = ksp->ks_next;
    }

    kstat_close(kc);
    close(sock);
    return py_retdict;

error:
    Py_XDECREF(py_ifc_info);
    Py_DECREF(py_retdict);
    if (kc != NULL)
        kstat_close(kc);
    if (sock != -1) {
        close(sock);
    }
    return NULL;
}


/*
 * Return TCP and UDP connections opened by process.
 * UNIX sockets are excluded.
 *
 * Thanks to:
 * https://github.com/DavidGriffith/finx/blob/master/
 *     nxsensor-3.5.0-1/src/sysdeps/solaris.c
 * ...and:
 * https://hg.java.net/hg/solaris~on-src/file/tip/usr/src/cmd/
 *     cmd-inet/usr.bin/netstat/netstat.c
 */
static PyObject *
psutil_net_connections(PyObject *self, PyObject *args) {
    long pid;
    int sd = 0;
    mib2_tcpConnEntry_t *tp = NULL;
    mib2_udpEntry_t     *ude;
#if defined(AF_INET6)
    mib2_tcp6ConnEntry_t *tp6;
    mib2_udp6Entry_t     *ude6;
#endif
    char buf[512];
    int i, flags, getcode, num_ent, state;
    char lip[200], rip[200];
    int lport, rport;
    int processed_pid;
    int databuf_init = 0;
    struct strbuf ctlbuf, databuf;
    struct T_optmgmt_req *tor = (struct T_optmgmt_req *)buf;
    struct T_optmgmt_ack *toa = (struct T_optmgmt_ack *)buf;
    struct T_error_ack   *tea = (struct T_error_ack *)buf;
    struct opthdr        *mibhdr;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_laddr = NULL;
    PyObject *py_raddr = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;

    sd = open("/dev/arp", O_RDWR);
    if (sd == -1) {
        PyErr_SetFromErrnoWithFilename(PyExc_OSError, "/dev/arp");
        goto error;
    }

    /*
    XXX - These 2 are used in ifconfig.c but they seem unnecessary
    ret = ioctl(sd, I_PUSH, "tcp");
    if (ret == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    ret = ioctl(sd, I_PUSH, "udp");
    if (ret == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    */

    // OK, this mess is basically copied and pasted from nxsensor project
    // which copied and pasted it from netstat source code, mibget()
    // function.  Also see:
    // http://stackoverflow.com/questions/8723598/
    tor->PRIM_type = T_SVR4_OPTMGMT_REQ;
    tor->OPT_offset = sizeof (struct T_optmgmt_req);
    tor->OPT_length = sizeof (struct opthdr);
    tor->MGMT_flags = T_CURRENT;
    mibhdr = (struct opthdr *)&tor[1];
    mibhdr->level = EXPER_IP_AND_ALL_IRES;
    mibhdr->name  = 0;
    mibhdr->len   = 0;

    ctlbuf.buf = buf;
    ctlbuf.len = tor->OPT_offset + tor->OPT_length;
    flags = 0;  // request to be sent in non-priority

    if (putmsg(sd, &ctlbuf, (struct strbuf *)0, flags) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    mibhdr = (struct opthdr *)&toa[1];
    ctlbuf.maxlen = sizeof (buf);

    for (;;) {
        flags = 0;
        getcode = getmsg(sd, &ctlbuf, (struct strbuf *)0, &flags);

        if (getcode != MOREDATA ||
                ctlbuf.len < sizeof (struct T_optmgmt_ack) ||
                toa->PRIM_type != T_OPTMGMT_ACK ||
                toa->MGMT_flags != T_SUCCESS)
        {
            break;
        }
        if (ctlbuf.len >= sizeof (struct T_error_ack) &&
                tea->PRIM_type == T_ERROR_ACK)
        {
            PyErr_SetString(PyExc_RuntimeError, "ERROR_ACK");
            goto error;
        }
        if (getcode == 0 &&
                ctlbuf.len >= sizeof (struct T_optmgmt_ack) &&
                toa->PRIM_type == T_OPTMGMT_ACK &&
                toa->MGMT_flags == T_SUCCESS)
        {
            PyErr_SetString(PyExc_RuntimeError, "ERROR_T_OPTMGMT_ACK");
            goto error;
        }

        databuf.maxlen = mibhdr->len;
        databuf.len = 0;
        databuf.buf = (char *)malloc((int)mibhdr->len);
        if (!databuf.buf) {
            PyErr_NoMemory();
            goto error;
        }
        databuf_init = 1;

        flags = 0;
        getcode = getmsg(sd, (struct strbuf *)0, &databuf, &flags);
        if (getcode < 0) {
            PyErr_SetFromErrno(PyExc_OSError);
            goto error;
        }

        // TCPv4
        if (mibhdr->level == MIB2_TCP && mibhdr->name == MIB2_TCP_13) {
            tp = (mib2_tcpConnEntry_t *)databuf.buf;
            num_ent = mibhdr->len / sizeof(mib2_tcpConnEntry_t);
            for (i = 0; i < num_ent; i++, tp++) {
                processed_pid = tp->tcpConnCreationProcess;
                if (pid != -1 && processed_pid != pid)
                    continue;
                // construct local/remote addresses
                inet_ntop(AF_INET, &tp->tcpConnLocalAddress, lip, sizeof(lip));
                inet_ntop(AF_INET, &tp->tcpConnRemAddress, rip, sizeof(rip));
                lport = tp->tcpConnLocalPort;
                rport = tp->tcpConnRemPort;

                // contruct python tuple/list
                py_laddr = Py_BuildValue("(si)", lip, lport);
                if (!py_laddr)
                    goto error;
                if (rport != 0)
                    py_raddr = Py_BuildValue("(si)", rip, rport);
                else {
                    py_raddr = Py_BuildValue("()");
                }
                if (!py_raddr)
                    goto error;
                state = tp->tcpConnEntryInfo.ce_state;

                // add item
                py_tuple = Py_BuildValue("(iiiNNiI)", -1, AF_INET, SOCK_STREAM,
                                         py_laddr, py_raddr, state,
                                         processed_pid);
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
        }
#if defined(AF_INET6)
        // TCPv6
        else if (mibhdr->level == MIB2_TCP6 && mibhdr->name == MIB2_TCP6_CONN)
        {
            tp6 = (mib2_tcp6ConnEntry_t *)databuf.buf;
            num_ent = mibhdr->len / sizeof(mib2_tcp6ConnEntry_t);

            for (i = 0; i < num_ent; i++, tp6++) {
                processed_pid = tp6->tcp6ConnCreationProcess;
                if (pid != -1 && processed_pid != pid)
                    continue;
                // construct local/remote addresses
                inet_ntop(AF_INET6, &tp6->tcp6ConnLocalAddress, lip, sizeof(lip));
                inet_ntop(AF_INET6, &tp6->tcp6ConnRemAddress, rip, sizeof(rip));
                lport = tp6->tcp6ConnLocalPort;
                rport = tp6->tcp6ConnRemPort;

                // contruct python tuple/list
                py_laddr = Py_BuildValue("(si)", lip, lport);
                if (!py_laddr)
                    goto error;
                if (rport != 0)
                    py_raddr = Py_BuildValue("(si)", rip, rport);
                else
                    py_raddr = Py_BuildValue("()");
                if (!py_raddr)
                    goto error;
                state = tp6->tcp6ConnEntryInfo.ce_state;

                // add item
                py_tuple = Py_BuildValue("(iiiNNiI)", -1, AF_INET6, SOCK_STREAM,
                                         py_laddr, py_raddr, state, processed_pid);
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
        }
#endif
        // UDPv4
        else if (mibhdr->level == MIB2_UDP || mibhdr->level == MIB2_UDP_ENTRY) {
            ude = (mib2_udpEntry_t *)databuf.buf;
            num_ent = mibhdr->len / sizeof(mib2_udpEntry_t);
            for (i = 0; i < num_ent; i++, ude++) {
                processed_pid = ude->udpCreationProcess;
                if (pid != -1 && processed_pid != pid)
                    continue;
                // XXX Very ugly hack! It seems we get here only the first
                // time we bump into a UDPv4 socket.  PID is a very high
                // number (clearly impossible) and the address does not
                // belong to any valid interface.  Not sure what else
                // to do other than skipping.
                if (processed_pid > 131072)
                    continue;
                inet_ntop(AF_INET, &ude->udpLocalAddress, lip, sizeof(lip));
                lport = ude->udpLocalPort;
                py_laddr = Py_BuildValue("(si)", lip, lport);
                if (!py_laddr)
                    goto error;
                py_raddr = Py_BuildValue("()");
                if (!py_raddr)
                    goto error;
                py_tuple = Py_BuildValue("(iiiNNiI)", -1, AF_INET, SOCK_DGRAM,
                                         py_laddr, py_raddr, PSUTIL_CONN_NONE,
                                         processed_pid);
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
        }
#if defined(AF_INET6)
        // UDPv6
        else if (mibhdr->level == MIB2_UDP6 ||
                    mibhdr->level == MIB2_UDP6_ENTRY)
            {
            ude6 = (mib2_udp6Entry_t *)databuf.buf;
            num_ent = mibhdr->len / sizeof(mib2_udp6Entry_t);
            for (i = 0; i < num_ent; i++, ude6++) {
                processed_pid = ude6->udp6CreationProcess;
                if (pid != -1 && processed_pid != pid)
                    continue;
                inet_ntop(AF_INET6, &ude6->udp6LocalAddress, lip, sizeof(lip));
                lport = ude6->udp6LocalPort;
                py_laddr = Py_BuildValue("(si)", lip, lport);
                if (!py_laddr)
                    goto error;
                py_raddr = Py_BuildValue("()");
                if (!py_raddr)
                    goto error;
                py_tuple = Py_BuildValue("(iiiNNiI)", -1, AF_INET6, SOCK_DGRAM,
                                         py_laddr, py_raddr, PSUTIL_CONN_NONE,
                                         processed_pid);
                if (!py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
            }
        }
#endif
        free(databuf.buf);
    }

    close(sd);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_laddr);
    Py_XDECREF(py_raddr);
    Py_DECREF(py_retlist);
    if (databuf_init == 1)
        free(databuf.buf);
    if (sd != 0)
        close(sd);
    return NULL;
}


static PyObject *
psutil_boot_time(PyObject *self, PyObject *args) {
    float boot_time = 0.0;
    struct utmpx *ut;

    while (NULL != (ut = getutxent())) {
        if (ut->ut_type == BOOT_TIME) {
            boot_time = (float)ut->ut_tv.tv_sec;
            break;
        }
    }
    endutent();
    if (boot_time != 0.0) {
        return Py_BuildValue("f", boot_time);
    }
    else {
        PyErr_SetString(PyExc_RuntimeError, "can't determine boot time");
        return NULL;
    }
}


/*
 * Return the number of physical CPU cores on the system.
 */
static PyObject *
psutil_cpu_count_phys(PyObject *self, PyObject *args) {
    kstat_ctl_t *kc;
    kstat_t *ksp;
    int ncpus = 0;

    kc = kstat_open();
    if (kc == NULL)
        goto error;
    ksp = kstat_lookup(kc, "cpu_info", -1, NULL);
    if (ksp == NULL)
        goto error;

    for (ksp = kc->kc_chain; ksp; ksp = ksp->ks_next) {
        if (strcmp(ksp->ks_module, "cpu_info") != 0)
            continue;
        if (kstat_read(kc, ksp, NULL) == -1)
            goto error;
        ncpus += 1;
    }

    kstat_close(kc);
    if (ncpus > 0)
        return Py_BuildValue("i", ncpus);
    else
        goto error;

error:
    // mimic os.cpu_count()
    if (kc != NULL)
        kstat_close(kc);
    Py_RETURN_NONE;
}


/*
 * Return stats about a particular network
 * interface.  References:
 * https://github.com/dpaleino/wicd/blob/master/wicd/backends/be-ioctl.py
 * http://www.i-scream.org/libstatgrab/
 */
static PyObject*
psutil_net_if_stats(PyObject* self, PyObject* args) {
    kstat_ctl_t *kc = NULL;
    kstat_t *ksp;
    kstat_named_t *knp;
    int ret;
    int sock = -1;
    int duplex;
    int speed;

    PyObject *py_retdict = PyDict_New();
    PyObject *py_ifc_info = NULL;
    PyObject *py_is_up = NULL;

    if (py_retdict == NULL)
        return NULL;
    kc = kstat_open();
    if (kc == NULL)
        goto error;
    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (ksp = kc->kc_chain; ksp; ksp = ksp->ks_next) {
        if (strcmp(ksp->ks_class, "net") == 0) {
            struct lifreq ifr;

            kstat_read(kc, ksp, NULL);
            if (ksp->ks_type != KSTAT_TYPE_NAMED)
                continue;
            if (strcmp(ksp->ks_class, "net") != 0)
                continue;

            strncpy(ifr.lifr_name, ksp->ks_name, sizeof(ifr.lifr_name));
            ret = ioctl(sock, SIOCGLIFFLAGS, &ifr);
            if (ret == -1)
                continue;  // not a network interface

            // is up?
            if ((ifr.lifr_flags & IFF_UP) != 0) {
                if ((knp = kstat_data_lookup(ksp, "link_up")) != NULL) {
                    if (knp->value.ui32 != 0u)
                        py_is_up = Py_True;
                    else
                        py_is_up = Py_False;
                }
                else {
                    py_is_up = Py_True;
                }
            }
            else {
                py_is_up = Py_False;
            }
            Py_INCREF(py_is_up);

            // duplex
            duplex = 0;  // unknown
            if ((knp = kstat_data_lookup(ksp, "link_duplex")) != NULL) {
                if (knp->value.ui32 == 1)
                    duplex = 1;  // half
                else if (knp->value.ui32 == 2)
                    duplex = 2;  // full
            }

            // speed
            if ((knp = kstat_data_lookup(ksp, "ifspeed")) != NULL)
                // expressed in bits per sec, we want mega bits per sec
                speed = (int)knp->value.ui64 / 1000000;
            else
                speed = 0;

            // mtu
            ret = ioctl(sock, SIOCGLIFMTU, &ifr);
            if (ret == -1)
                goto error;

            py_ifc_info = Py_BuildValue("(Oiii)", py_is_up, duplex, speed,
                                        ifr.lifr_mtu);
            if (!py_ifc_info)
                goto error;
            if (PyDict_SetItemString(py_retdict, ksp->ks_name, py_ifc_info))
                goto error;
            Py_DECREF(py_ifc_info);
        }
    }

    close(sock);
    kstat_close(kc);
    return py_retdict;

error:
    Py_XDECREF(py_is_up);
    Py_XDECREF(py_ifc_info);
    Py_DECREF(py_retdict);
    if (sock != -1)
        close(sock);
    if (kc != NULL)
        kstat_close(kc);
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


/*
 * Return CPU statistics.
 */
static PyObject *
psutil_cpu_stats(PyObject *self, PyObject *args) {
    kstat_ctl_t *kc;
    kstat_t *ksp;
    cpu_stat_t cs;
    unsigned int ctx_switches = 0;
    unsigned int interrupts = 0;
    unsigned int traps = 0;
    unsigned int syscalls = 0;

    kc = kstat_open();
    if (kc == NULL) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (ksp = kc->kc_chain; ksp != NULL; ksp = ksp->ks_next) {
        if (strcmp(ksp->ks_module, "cpu_stat") == 0) {
            if (kstat_read(kc, ksp, &cs) == -1) {
                PyErr_SetFromErrno(PyExc_OSError);
                goto error;
            }
            // voluntary + involuntary
            ctx_switches += cs.cpu_sysinfo.pswitch + cs.cpu_sysinfo.inv_swtch;
            interrupts += cs.cpu_sysinfo.intr;
            traps += cs.cpu_sysinfo.trap;
            syscalls += cs.cpu_sysinfo.syscall;
        }
    }

    kstat_close(kc);
    return Py_BuildValue(
        "IIII", ctx_switches, interrupts, syscalls, traps);

error:
    if (kc != NULL)
        kstat_close(kc);
    return NULL;
}


/*
 * define the psutil C module methods and initialize the module.
 */
static PyMethodDef
PsutilMethods[] = {

    // --- process-related functions
    {"proc_basic_info", psutil_proc_basic_info, METH_VARARGS,
     "Return process ppid, rss, vms, ctime, nice, nthreads, status and tty"},
    {"proc_name_and_args", psutil_proc_name_and_args, METH_VARARGS,
     "Return process name and args."},
    {"proc_cpu_times", psutil_proc_cpu_times, METH_VARARGS,
     "Return process user and system CPU times."},
    {"proc_cred", psutil_proc_cred, METH_VARARGS,
     "Return process uids/gids."},
    {"query_process_thread", psutil_proc_query_thread, METH_VARARGS,
     "Return info about a process thread"},
    {"proc_memory_maps", psutil_proc_memory_maps, METH_VARARGS,
     "Return process memory mappings"},
    {"proc_num_ctx_switches", psutil_proc_num_ctx_switches, METH_VARARGS,
     "Return the number of context switches performed by process"},
    {"proc_cpu_num", psutil_proc_cpu_num, METH_VARARGS,
     "Return what CPU the process is on"},

    // --- system-related functions
    {"swap_mem", psutil_swap_mem, METH_VARARGS,
     "Return information about system swap memory."},
    {"users", psutil_users, METH_VARARGS,
     "Return currently connected users."},
    {"disk_partitions", psutil_disk_partitions, METH_VARARGS,
     "Return disk partitions."},
    {"per_cpu_times", psutil_per_cpu_times, METH_VARARGS,
     "Return system per-CPU times."},
    {"disk_io_counters", psutil_disk_io_counters, METH_VARARGS,
     "Return a Python dict of tuples for disk I/O statistics."},
    {"net_io_counters", psutil_net_io_counters, METH_VARARGS,
     "Return a Python dict of tuples for network I/O statistics."},
    {"boot_time", psutil_boot_time, METH_VARARGS,
     "Return system boot time in seconds since the EPOCH."},
    {"cpu_count_phys", psutil_cpu_count_phys, METH_VARARGS,
     "Return the number of physical CPUs on the system."},
    {"net_connections", psutil_net_connections, METH_VARARGS,
     "Return TCP and UDP syste-wide open connections."},
    {"net_if_stats", psutil_net_if_stats, METH_VARARGS,
     "Return NIC stats (isup, duplex, speed, mtu)"},
    {"cpu_stats", psutil_cpu_stats, METH_VARARGS,
     "Return CPU statistics"},

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
psutil_sunos_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int
psutil_sunos_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "psutil_sunos",
    NULL,
    sizeof(struct module_state),
    PsutilMethods,
    NULL,
    psutil_sunos_traverse,
    psutil_sunos_clear,
    NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit__psutil_sunos(void)

#else
#define INITERROR return

void init_psutil_sunos(void)
#endif
{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("_psutil_sunos", PsutilMethods);
#endif
    PyModule_AddIntConstant(module, "version", PSUTIL_VERSION);

    PyModule_AddIntConstant(module, "SSLEEP", SSLEEP);
    PyModule_AddIntConstant(module, "SRUN", SRUN);
    PyModule_AddIntConstant(module, "SZOMB", SZOMB);
    PyModule_AddIntConstant(module, "SSTOP", SSTOP);
    PyModule_AddIntConstant(module, "SIDL", SIDL);
    PyModule_AddIntConstant(module, "SONPROC", SONPROC);
    PyModule_AddIntConstant(module, "SWAIT", SWAIT);

    PyModule_AddIntConstant(module, "PRNODEV", PRNODEV);  // for process tty

    PyModule_AddIntConstant(module, "TCPS_CLOSED", TCPS_CLOSED);
    PyModule_AddIntConstant(module, "TCPS_CLOSING", TCPS_CLOSING);
    PyModule_AddIntConstant(module, "TCPS_CLOSE_WAIT", TCPS_CLOSE_WAIT);
    PyModule_AddIntConstant(module, "TCPS_LISTEN", TCPS_LISTEN);
    PyModule_AddIntConstant(module, "TCPS_ESTABLISHED", TCPS_ESTABLISHED);
    PyModule_AddIntConstant(module, "TCPS_SYN_SENT", TCPS_SYN_SENT);
    PyModule_AddIntConstant(module, "TCPS_SYN_RCVD", TCPS_SYN_RCVD);
    PyModule_AddIntConstant(module, "TCPS_FIN_WAIT_1", TCPS_FIN_WAIT_1);
    PyModule_AddIntConstant(module, "TCPS_FIN_WAIT_2", TCPS_FIN_WAIT_2);
    PyModule_AddIntConstant(module, "TCPS_LAST_ACK", TCPS_LAST_ACK);
    PyModule_AddIntConstant(module, "TCPS_TIME_WAIT", TCPS_TIME_WAIT);
    // sunos specific
    PyModule_AddIntConstant(module, "TCPS_IDLE", TCPS_IDLE);
    // sunos specific
    PyModule_AddIntConstant(module, "TCPS_BOUND", TCPS_BOUND);
    PyModule_AddIntConstant(module, "PSUTIL_CONN_NONE", PSUTIL_CONN_NONE);

    if (module == NULL)
        INITERROR;
#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
