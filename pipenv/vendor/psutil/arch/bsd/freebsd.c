/*
 * Copyright (c) 2009, Jay Loden, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Helper functions related to fetching process information.
 * Used by _psutil_bsd module methods.
 */

#include <Python.h>
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/sysctl.h>
#include <sys/param.h>
#include <sys/user.h>
#include <sys/proc.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/vmmeter.h>  // needed for vmtotal struct
#include <devstat.h>  // for swap mem
#include <libutil.h>  // process open files, shared libs (kinfo_getvmmap), cwd
#include <sys/cpuset.h>

#include "../../_psutil_common.h"


#define PSUTIL_TV2DOUBLE(t)    ((t).tv_sec + (t).tv_usec / 1000000.0)
#define PSUTIL_BT2MSEC(bt) (bt.sec * 1000 + (((uint64_t) 1000000000 * (uint32_t) \
        (bt.frac >> 32) ) >> 32 ) / 1000000)
#ifndef _PATH_DEVNULL
#define _PATH_DEVNULL "/dev/null"
#endif


// ============================================================================
// Utility functions
// ============================================================================


int
psutil_kinfo_proc(const pid_t pid, struct kinfo_proc *proc) {
    // Fills a kinfo_proc struct based on process pid.
    int mib[4];
    size_t size;
    mib[0] = CTL_KERN;
    mib[1] = KERN_PROC;
    mib[2] = KERN_PROC_PID;
    mib[3] = pid;

    size = sizeof(struct kinfo_proc);
    if (sysctl((int *)mib, 4, proc, &size, NULL, 0) == -1) {
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


// remove spaces from string
static void psutil_remove_spaces(char *str) {
    char *p1 = str;
    char *p2 = str;
    do
        while (*p2 == ' ')
            p2++;
    while ((*p1++ = *p2++));
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
    int err;
    struct kinfo_proc *result;
    int done;
    int name[] = { CTL_KERN, KERN_PROC, KERN_PROC_PROC, 0 };
    size_t length;

    assert( procList != NULL);
    assert(*procList == NULL);
    assert(procCount != NULL);

    *procCount = 0;

    /*
     * We start by calling sysctl with result == NULL and length == 0.
     * That will succeed, and set length to the appropriate length.
     * We then allocate a buffer of that size and call sysctl again
     * with that buffer.  If that succeeds, we're done.  If that fails
     * with ENOMEM, we have to throw away our buffer and loop.  Note
     * that the loop causes use to call sysctl with NULL again; this
     * is necessary because the ENOMEM failure case sets length to
     * the amount of data returned, not the amount of data that
     * could have been returned.
     */
    result = NULL;
    done = 0;
    do {
        assert(result == NULL);
        // Call sysctl with a NULL buffer.
        length = 0;
        err = sysctl((int *)name, (sizeof(name) / sizeof(*name)) - 1,
                     NULL, &length, NULL, 0);
        if (err == -1)
            err = errno;

        // Allocate an appropriately sized buffer based on the results
        // from the previous call.
        if (err == 0) {
            result = malloc(length);
            if (result == NULL)
                err = ENOMEM;
        }

        // Call sysctl again with the new buffer.  If we get an ENOMEM
        // error, toss away our buffer and start again.
        if (err == 0) {
            err = sysctl((int *) name, (sizeof(name) / sizeof(*name)) - 1,
                         result, &length, NULL, 0);
            if (err == -1)
                err = errno;
            if (err == 0) {
                done = 1;
            }
            else if (err == ENOMEM) {
                assert(result != NULL);
                free(result);
                result = NULL;
                err = 0;
            }
        }
    } while (err == 0 && ! done);

    // Clean up and establish post conditions.
    if (err != 0 && result != NULL) {
        free(result);
        result = NULL;
    }

    *procList = result;
    *procCount = length / sizeof(struct kinfo_proc);

    assert((err == 0) == (*procList != NULL));
    return err;
}


/*
 * XXX no longer used; it probably makese sense to remove it.
 * Borrowed from psi Python System Information project
 *
 * Get command arguments and environment variables.
 *
 * Based on code from ps.
 *
 * Returns:
 *      0 for success;
 *      -1 for failure (Exception raised);
 *      1 for insufficient privileges.
 */
static char
*psutil_get_cmd_args(long pid, size_t *argsize) {
    int mib[4], argmax;
    size_t size = sizeof(argmax);
    char *procargs = NULL;

    // Get the maximum process arguments size.
    mib[0] = CTL_KERN;
    mib[1] = KERN_ARGMAX;

    size = sizeof(argmax);
    if (sysctl(mib, 2, &argmax, &size, NULL, 0) == -1)
        return NULL;

    // Allocate space for the arguments.
    procargs = (char *)malloc(argmax);
    if (procargs == NULL) {
        PyErr_NoMemory();
        return NULL;
    }

    /*
     * Make a sysctl() call to get the raw argument space of the process.
     */
    mib[0] = CTL_KERN;
    mib[1] = KERN_PROC;
    mib[2] = KERN_PROC_ARGS;
    mib[3] = pid;

    size = argmax;
    if (sysctl(mib, 4, procargs, &size, NULL, 0) == -1) {
        free(procargs);
        return NULL;       // Insufficient privileges
    }

    // return string and set the length of arguments
    *argsize = size;
    return procargs;
}


// returns the command line as a python list object
PyObject *
psutil_get_cmdline(long pid) {
    char *argstr = NULL;
    int pos = 0;
    size_t argsize = 0;
    PyObject *py_retlist = Py_BuildValue("[]");
    PyObject *py_arg = NULL;

    if (pid < 0)
        return py_retlist;
    argstr = psutil_get_cmd_args(pid, &argsize);
    if (argstr == NULL)
        goto error;

    // args are returned as a flattened string with \0 separators between
    // arguments add each string to the list then step forward to the next
    // separator
    if (argsize > 0) {
        while (pos < argsize) {
#if PY_MAJOR_VERSION >= 3
            py_arg = PyUnicode_DecodeFSDefault(&argstr[pos]);
#else
            py_arg = Py_BuildValue("s", &argstr[pos]);
#endif
            if (!py_arg)
                goto error;
            if (PyList_Append(py_retlist, py_arg))
                goto error;
            Py_DECREF(py_arg);
            pos = pos + strlen(&argstr[pos]) + 1;
        }
    }

    free(argstr);
    return py_retlist;

error:
    Py_XDECREF(py_arg);
    Py_DECREF(py_retlist);
    if (argstr != NULL)
        free(argstr);
    return NULL;
}


/*
 * Return process pathname executable.
 * Thanks to Robert N. M. Watson:
 * http://fxr.googlebit.com/source/usr.bin/procstat/procstat_bin.c?v=8-CURRENT
 */
PyObject *
psutil_proc_exe(PyObject *self, PyObject *args) {
    long pid;
    char pathname[PATH_MAX];
    int error;
    int mib[4];
    int ret;
    size_t size;
    const char *encoding_errs;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    mib[0] = CTL_KERN;
    mib[1] = KERN_PROC;
    mib[2] = KERN_PROC_PATHNAME;
    mib[3] = pid;

    size = sizeof(pathname);
    error = sysctl(mib, 4, pathname, &size, NULL, 0);
    if (error == -1) {
        if (errno == ENOENT) {
            // see: https://github.com/giampaolo/psutil/issues/907
            return Py_BuildValue("s", "");
        }
        else {
            PyErr_SetFromErrno(PyExc_OSError);
            return NULL;
        }
    }
    if (size == 0 || strlen(pathname) == 0) {
        ret = psutil_pid_exists(pid);
        if (ret == -1)
            return NULL;
        else if (ret == 0)
            return NoSuchProcess();
        else
            strcpy(pathname, "");
    }

#if PY_MAJOR_VERSION >= 3
    return PyUnicode_DecodeFSDefault(pathname);
#else
    return Py_BuildValue("s", pathname);
#endif

}


PyObject *
psutil_proc_num_threads(PyObject *self, PyObject *args) {
    // Return number of threads used by process as a Python integer.
    long pid;
    struct kinfo_proc kp;
    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (psutil_kinfo_proc(pid, &kp) == -1)
        return NULL;
    return Py_BuildValue("l", (long)kp.ki_numthreads);
}


PyObject *
psutil_proc_threads(PyObject *self, PyObject *args) {
    // Retrieves all threads used by process returning a list of tuples
    // including thread id, user time and system time.
    // Thanks to Robert N. M. Watson:
    // http://fxr.googlebit.com/source/usr.bin/procstat/
    //     procstat_threads.c?v=8-CURRENT
    long pid;
    int mib[4];
    struct kinfo_proc *kip = NULL;
    struct kinfo_proc *kipp = NULL;
    int error;
    unsigned int i;
    size_t size;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;

    // we need to re-query for thread information, so don't use *kipp
    mib[0] = CTL_KERN;
    mib[1] = KERN_PROC;
    mib[2] = KERN_PROC_PID | KERN_PROC_INC_THREAD;
    mib[3] = pid;

    size = 0;
    error = sysctl(mib, 4, NULL, &size, NULL, 0);
    if (error == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    if (size == 0) {
        NoSuchProcess();
        goto error;
    }

    kip = malloc(size);
    if (kip == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    error = sysctl(mib, 4, kip, &size, NULL, 0);
    if (error == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }
    if (size == 0) {
        NoSuchProcess();
        goto error;
    }

    for (i = 0; i < size / sizeof(*kipp); i++) {
        kipp = &kip[i];
        py_tuple = Py_BuildValue("Idd",
                                 kipp->ki_tid,
                                 PSUTIL_TV2DOUBLE(kipp->ki_rusage.ru_utime),
                                 PSUTIL_TV2DOUBLE(kipp->ki_rusage.ru_stime));
        if (py_tuple == NULL)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }
    free(kip);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (kip != NULL)
        free(kip);
    return NULL;
}


PyObject *
psutil_cpu_count_phys(PyObject *self, PyObject *args) {
    // Return an XML string from which we'll determine the number of
    // physical CPU cores in the system.
    void *topology = NULL;
    size_t size = 0;
    PyObject *py_str;

    if (sysctlbyname("kern.sched.topology_spec", NULL, &size, NULL, 0))
        goto error;

    topology = malloc(size);
    if (!topology) {
        PyErr_NoMemory();
        return NULL;
    }

    if (sysctlbyname("kern.sched.topology_spec", topology, &size, NULL, 0))
        goto error;

    py_str = Py_BuildValue("s", topology);
    free(topology);
    return py_str;

error:
    if (topology != NULL)
        free(topology);
    Py_RETURN_NONE;
}


/*
 * Return virtual memory usage statistics.
 */
PyObject *
psutil_virtual_mem(PyObject *self, PyObject *args) {
    unsigned long  total;
    unsigned int   active, inactive, wired, cached, free;
    size_t         size = sizeof(total);
    struct vmtotal vm;
    int            mib[] = {CTL_VM, VM_METER};
    long           pagesize = getpagesize();
#if __FreeBSD_version > 702101
    long buffers;
#else
    int buffers;
#endif
    size_t buffers_size = sizeof(buffers);

    if (sysctlbyname("hw.physmem", &total, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.vm.v_active_count", &active, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.vm.v_inactive_count",
                     &inactive, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.vm.v_wire_count", &wired, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.vm.v_cache_count", &cached, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.vm.v_free_count", &free, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vfs.bufspace", &buffers, &buffers_size, NULL, 0))
        goto error;

    size = sizeof(vm);
    if (sysctl(mib, 2, &vm, &size, NULL, 0) != 0)
        goto error;

    return Py_BuildValue("KKKKKKKK",
        (unsigned long long) total,
        (unsigned long long) free     * pagesize,
        (unsigned long long) active   * pagesize,
        (unsigned long long) inactive * pagesize,
        (unsigned long long) wired    * pagesize,
        (unsigned long long) cached   * pagesize,
        (unsigned long long) buffers,
        (unsigned long long) (vm.t_vmshr + vm.t_rmshr) * pagesize  // shared
    );

error:
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


PyObject *
psutil_swap_mem(PyObject *self, PyObject *args) {
    // Return swap memory stats (see 'swapinfo' cmdline tool)
    kvm_t *kd;
    struct kvm_swap kvmsw[1];
    unsigned int swapin, swapout, nodein, nodeout;
    size_t size = sizeof(unsigned int);

    kd = kvm_open(NULL, _PATH_DEVNULL, NULL, O_RDONLY, "kvm_open failed");
    if (kd == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "kvm_open() syscall failed");
        return NULL;
    }

    if (kvm_getswapinfo(kd, kvmsw, 1, 0) < 0) {
        kvm_close(kd);
        PyErr_SetString(PyExc_RuntimeError,
                        "kvm_getswapinfo() syscall failed");
        return NULL;
    }

    kvm_close(kd);

    if (sysctlbyname("vm.stats.vm.v_swapin", &swapin, &size, NULL, 0) == -1)
        goto sbn_error;
    if (sysctlbyname("vm.stats.vm.v_swapout", &swapout, &size, NULL, 0) == -1)
        goto sbn_error;
    if (sysctlbyname("vm.stats.vm.v_vnodein", &nodein, &size, NULL, 0) == -1)
        goto sbn_error;
    if (sysctlbyname("vm.stats.vm.v_vnodeout", &nodeout, &size, NULL, 0) == -1)
        goto sbn_error;

    return Py_BuildValue("(iiiII)",
                         kvmsw[0].ksw_total,                     // total
                         kvmsw[0].ksw_used,                      // used
                         kvmsw[0].ksw_total - kvmsw[0].ksw_used, // free
                         swapin + swapout,                       // swap in
                         nodein + nodeout);                      // swap out

sbn_error:
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


#if defined(__FreeBSD_version) && __FreeBSD_version >= 800000
PyObject *
psutil_proc_cwd(PyObject *self, PyObject *args) {
    long pid;
    struct kinfo_file *freep = NULL;
    struct kinfo_file *kif;
    struct kinfo_proc kipp;
    const char *encoding_errs;
    PyObject *py_path = NULL;

    int i, cnt;

    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;
    if (psutil_kinfo_proc(pid, &kipp) == -1)
        goto error;

    errno = 0;
    freep = kinfo_getfile(pid, &cnt);
    if (freep == NULL) {
        psutil_raise_for_pid(pid, "kinfo_getfile() failed");
        goto error;
    }

    for (i = 0; i < cnt; i++) {
        kif = &freep[i];
        if (kif->kf_fd == KF_FD_TYPE_CWD) {
#if PY_MAJOR_VERSION >= 3
            py_path = PyUnicode_DecodeFSDefault(kif->kf_path);
#else
            py_path = Py_BuildValue("s", kif->kf_path);
#endif
            if (!py_path)
                goto error;
            break;
        }
    }
    /*
     * For lower pids it seems we can't retrieve any information
     * (lsof can't do that it either).  Since this happens even
     * as root we return an empty string instead of AccessDenied.
     */
    if (py_path == NULL)
        py_path = Py_BuildValue("s", "");
    free(freep);
    return py_path;

error:
    Py_XDECREF(py_path);
    if (freep != NULL)
        free(freep);
    return NULL;
}
#endif


#if defined(__FreeBSD_version) && __FreeBSD_version >= 800000
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
#endif


PyObject *
psutil_per_cpu_times(PyObject *self, PyObject *args) {
    static int maxcpus;
    int mib[2];
    int ncpu;
    size_t len;
    size_t size;
    int i;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_cputime = NULL;

    if (py_retlist == NULL)
        return NULL;

    // retrieve maxcpus value
    size = sizeof(maxcpus);
    if (sysctlbyname("kern.smp.maxcpus", &maxcpus, &size, NULL, 0) < 0) {
        Py_DECREF(py_retlist);
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }
    long cpu_time[maxcpus][CPUSTATES];

    // retrieve the number of cpus
    mib[0] = CTL_HW;
    mib[1] = HW_NCPU;
    len = sizeof(ncpu);
    if (sysctl(mib, 2, &ncpu, &len, NULL, 0) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    // per-cpu info
    size = sizeof(cpu_time);
    if (sysctlbyname("kern.cp_times", &cpu_time, &size, NULL, 0) == -1) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    for (i = 0; i < ncpu; i++) {
        py_cputime = Py_BuildValue(
            "(ddddd)",
            (double)cpu_time[i][CP_USER] / CLOCKS_PER_SEC,
            (double)cpu_time[i][CP_NICE] / CLOCKS_PER_SEC,
            (double)cpu_time[i][CP_SYS] / CLOCKS_PER_SEC,
            (double)cpu_time[i][CP_IDLE] / CLOCKS_PER_SEC,
            (double)cpu_time[i][CP_INTR] / CLOCKS_PER_SEC);
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
    int i;
    struct statinfo stats;

    PyObject *py_retdict = PyDict_New();
    PyObject *py_disk_info = NULL;

    if (py_retdict == NULL)
        return NULL;
    if (devstat_checkversion(NULL) < 0) {
        PyErr_Format(PyExc_RuntimeError,
                     "devstat_checkversion() syscall failed");
        goto error;
    }

    stats.dinfo = (struct devinfo *)malloc(sizeof(struct devinfo));
    if (stats.dinfo == NULL) {
        PyErr_NoMemory();
        goto error;
    }
    bzero(stats.dinfo, sizeof(struct devinfo));

    if (devstat_getdevs(NULL, &stats) == -1) {
        PyErr_Format(PyExc_RuntimeError, "devstat_getdevs() syscall failed");
        goto error;
    }

    for (i = 0; i < stats.dinfo->numdevs; i++) {
        py_disk_info = NULL;
        struct devstat current;
        char disk_name[128];
        current = stats.dinfo->devices[i];
        snprintf(disk_name, sizeof(disk_name), "%s%d",
                 current.device_name,
                 current.unit_number);

        py_disk_info = Py_BuildValue(
            "(KKKKLLL)",
            current.operations[DEVSTAT_READ],   // no reads
            current.operations[DEVSTAT_WRITE],  // no writes
            current.bytes[DEVSTAT_READ],        // bytes read
            current.bytes[DEVSTAT_WRITE],       // bytes written
            (long long) PSUTIL_BT2MSEC(current.duration[DEVSTAT_READ]),  // r time
            (long long) PSUTIL_BT2MSEC(current.duration[DEVSTAT_WRITE]),  // w time
            (long long) PSUTIL_BT2MSEC(current.busy_time)  // busy time
        );      // finished transactions
        if (!py_disk_info)
            goto error;
        if (PyDict_SetItemString(py_retdict, disk_name, py_disk_info))
            goto error;
        Py_DECREF(py_disk_info);
    }

    if (stats.dinfo->mem_ptr)
        free(stats.dinfo->mem_ptr);
    free(stats.dinfo);
    return py_retdict;

error:
    Py_XDECREF(py_disk_info);
    Py_DECREF(py_retdict);
    if (stats.dinfo != NULL)
        free(stats.dinfo);
    return NULL;
}


PyObject *
psutil_proc_memory_maps(PyObject *self, PyObject *args) {
    // Return a list of tuples for every process memory maps.
    //'procstat' cmdline utility has been used as an example.
    long pid;
    int ptrwidth;
    int i, cnt;
    char addr[1000];
    char perms[4];
    const char *path;
    struct kinfo_proc kp;
    struct kinfo_vmentry *freep = NULL;
    struct kinfo_vmentry *kve;
    ptrwidth = 2 * sizeof(void *);
    PyObject *py_tuple = NULL;
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;
    if (psutil_kinfo_proc(pid, &kp) == -1)
        goto error;

    errno = 0;
    freep = kinfo_getvmmap(pid, &cnt);
    if (freep == NULL) {
        psutil_raise_for_pid(pid, "kinfo_getvmmap() failed");
        goto error;
    }
    for (i = 0; i < cnt; i++) {
        py_tuple = NULL;
        kve = &freep[i];
        addr[0] = '\0';
        perms[0] = '\0';
        sprintf(addr, "%#*jx-%#*jx", ptrwidth, (uintmax_t)kve->kve_start,
                ptrwidth, (uintmax_t)kve->kve_end);
        psutil_remove_spaces(addr);
        strlcat(perms, kve->kve_protection & KVME_PROT_READ ? "r" : "-",
                sizeof(perms));
        strlcat(perms, kve->kve_protection & KVME_PROT_WRITE ? "w" : "-",
                sizeof(perms));
        strlcat(perms, kve->kve_protection & KVME_PROT_EXEC ? "x" : "-",
                sizeof(perms));

        if (strlen(kve->kve_path) == 0) {
            switch (kve->kve_type) {
                case KVME_TYPE_NONE:
                    path = "[none]";
                    break;
                case KVME_TYPE_DEFAULT:
                    path = "[default]";
                    break;
                case KVME_TYPE_VNODE:
                    path = "[vnode]";
                    break;
                case KVME_TYPE_SWAP:
                    path = "[swap]";
                    break;
                case KVME_TYPE_DEVICE:
                    path = "[device]";
                    break;
                case KVME_TYPE_PHYS:
                    path = "[phys]";
                    break;
                case KVME_TYPE_DEAD:
                    path = "[dead]";
                    break;
                case KVME_TYPE_SG:
                    path = "[sg]";
                    break;
                case KVME_TYPE_UNKNOWN:
                    path = "[unknown]";
                    break;
                default:
                    path = "[?]";
                    break;
            }
        }
        else {
            path = kve->kve_path;
        }

        py_tuple = Py_BuildValue("sssiiii",
            addr,                       // "start-end" address
            perms,                      // "rwx" permissions
            path,                       // path
            kve->kve_resident,          // rss
            kve->kve_private_resident,  // private
            kve->kve_ref_count,         // ref count
            kve->kve_shadow_count);     // shadow count
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }
    free(freep);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (freep != NULL)
        free(freep);
    return NULL;
}


PyObject*
psutil_proc_cpu_affinity_get(PyObject* self, PyObject* args) {
    // Get process CPU affinity.
    // Reference:
    // http://sources.freebsd.org/RELENG_9/src/usr.bin/cpuset/cpuset.c
    long pid;
    int ret;
    int i;
    cpuset_t mask;
    PyObject* py_retlist;
    PyObject* py_cpu_num;

    if (!PyArg_ParseTuple(args, "i", &pid))
        return NULL;
    ret = cpuset_getaffinity(CPU_LEVEL_WHICH, CPU_WHICH_PID, pid,
                             sizeof(mask), &mask);
    if (ret != 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    py_retlist = PyList_New(0);
    if (py_retlist == NULL)
        return NULL;

    for (i = 0; i < CPU_SETSIZE; i++) {
        if (CPU_ISSET(i, &mask)) {
            py_cpu_num = Py_BuildValue("i", i);
            if (py_cpu_num == NULL)
                goto error;
            if (PyList_Append(py_retlist, py_cpu_num))
                goto error;
        }
    }

    return py_retlist;

error:
    Py_XDECREF(py_cpu_num);
    Py_DECREF(py_retlist);
    return NULL;
}


PyObject *
psutil_proc_cpu_affinity_set(PyObject *self, PyObject *args) {
    // Set process CPU affinity.
    // Reference:
    // http://sources.freebsd.org/RELENG_9/src/usr.bin/cpuset/cpuset.c
    long pid;
    int i;
    int seq_len;
    int ret;
    cpuset_t cpu_set;
    PyObject *py_cpu_set;
    PyObject *py_cpu_seq = NULL;

    if (!PyArg_ParseTuple(args, "lO", &pid, &py_cpu_set))
        return NULL;

    py_cpu_seq = PySequence_Fast(py_cpu_set, "expected a sequence or integer");
    if (!py_cpu_seq)
        return NULL;
    seq_len = PySequence_Fast_GET_SIZE(py_cpu_seq);

    // calculate the mask
    CPU_ZERO(&cpu_set);
    for (i = 0; i < seq_len; i++) {
        PyObject *item = PySequence_Fast_GET_ITEM(py_cpu_seq, i);
#if PY_MAJOR_VERSION >= 3
        long value = PyLong_AsLong(item);
#else
        long value = PyInt_AsLong(item);
#endif
        if (value == -1 || PyErr_Occurred())
            goto error;
        CPU_SET(value, &cpu_set);
    }

    // set affinity
    ret = cpuset_setaffinity(CPU_LEVEL_WHICH, CPU_WHICH_PID, pid,
                             sizeof(cpu_set), &cpu_set);
    if (ret != 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    Py_DECREF(py_cpu_seq);
    Py_RETURN_NONE;

error:
    if (py_cpu_seq != NULL)
        Py_DECREF(py_cpu_seq);
    return NULL;
}


PyObject *
psutil_cpu_stats(PyObject *self, PyObject *args) {
    unsigned int v_soft;
    unsigned int v_intr;
    unsigned int v_syscall;
    unsigned int v_trap;
    unsigned int v_swtch;
    size_t size = sizeof(v_soft);

    if (sysctlbyname("vm.stats.sys.v_soft", &v_soft, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.sys.v_intr", &v_intr, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.sys.v_syscall", &v_syscall, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.sys.v_trap", &v_trap, &size, NULL, 0))
        goto error;
    if (sysctlbyname("vm.stats.sys.v_swtch", &v_swtch, &size, NULL, 0))
        goto error;

    return Py_BuildValue(
        "IIIII",
        v_swtch,  // ctx switches
        v_intr,  // interrupts
        v_soft,  // software interrupts
        v_syscall,  // syscalls
        v_trap  // traps
    );

error:
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


/*
 * Return battery information.
 */
PyObject *
psutil_sensors_battery(PyObject *self, PyObject *args) {
    int percent;
    int minsleft;
    int power_plugged;
    size_t size = sizeof(percent);

    if (sysctlbyname("hw.acpi.battery.life", &percent, &size, NULL, 0))
        goto error;
    if (sysctlbyname("hw.acpi.battery.time", &minsleft, &size, NULL, 0))
        goto error;
    if (sysctlbyname("hw.acpi.acline", &power_plugged, &size, NULL, 0))
        goto error;
    return Py_BuildValue("iii", percent, minsleft, power_plugged);

error:
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}
