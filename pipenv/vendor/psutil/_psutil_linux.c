/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Linux-specific functions.
 */

#ifndef _GNU_SOURCE
    #define _GNU_SOURCE 1
#endif
#include <Python.h>
#include <errno.h>
#include <stdlib.h>
#include <mntent.h>
#include <features.h>
#include <utmp.h>
#include <sched.h>
#include <linux/version.h>
#include <sys/syscall.h>
#include <sys/sysinfo.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/sockios.h>
#include <linux/if.h>

// see: https://github.com/giampaolo/psutil/issues/659
#ifdef PSUTIL_ETHTOOL_MISSING_TYPES
    #include <linux/types.h>
    typedef __u64 u64;
    typedef __u32 u32;
    typedef __u16 u16;
    typedef __u8 u8;
#endif
/* Avoid redefinition of struct sysinfo with musl libc */
#define _LINUX_SYSINFO_H
#include <linux/ethtool.h>

/* The minimum number of CPUs allocated in a cpu_set_t */
static const int NCPUS_START = sizeof(unsigned long) * CHAR_BIT;

// Linux >= 2.6.13
#define PSUTIL_HAVE_IOPRIO defined(__NR_ioprio_get) && defined(__NR_ioprio_set)

// Linux >= 2.6.36 (supposedly) and glibc >= 13
#define PSUTIL_HAVE_PRLIMIT \
    (LINUX_VERSION_CODE >= KERNEL_VERSION(2, 6, 36)) && \
    (__GLIBC__ >= 2 && __GLIBC_MINOR__ >= 13) && \
    defined(__NR_prlimit64)

#if PSUTIL_HAVE_PRLIMIT
    #define _FILE_OFFSET_BITS 64
    #include <time.h>
    #include <sys/resource.h>
#endif


// May happen on old RedHat versions, see:
// https://github.com/giampaolo/psutil/issues/607
#ifndef DUPLEX_UNKNOWN
    #define DUPLEX_UNKNOWN 0xff
#endif


#if PSUTIL_HAVE_IOPRIO
enum {
    IOPRIO_WHO_PROCESS = 1,
};

static inline int
ioprio_get(int which, int who) {
    return syscall(__NR_ioprio_get, which, who);
}

static inline int
ioprio_set(int which, int who, int ioprio) {
    return syscall(__NR_ioprio_set, which, who, ioprio);
}

#define IOPRIO_CLASS_SHIFT 13
#define IOPRIO_PRIO_MASK ((1UL << IOPRIO_CLASS_SHIFT) - 1)

#define IOPRIO_PRIO_CLASS(mask) ((mask) >> IOPRIO_CLASS_SHIFT)
#define IOPRIO_PRIO_DATA(mask) ((mask) & IOPRIO_PRIO_MASK)
#define IOPRIO_PRIO_VALUE(class, data) (((class) << IOPRIO_CLASS_SHIFT) | data)


/*
 * Return a (ioclass, iodata) Python tuple representing process I/O priority.
 */
static PyObject *
psutil_proc_ioprio_get(PyObject *self, PyObject *args) {
    long pid;
    int ioprio, ioclass, iodata;
    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    ioprio = ioprio_get(IOPRIO_WHO_PROCESS, pid);
    if (ioprio == -1)
        return PyErr_SetFromErrno(PyExc_OSError);
    ioclass = IOPRIO_PRIO_CLASS(ioprio);
    iodata = IOPRIO_PRIO_DATA(ioprio);
    return Py_BuildValue("ii", ioclass, iodata);
}


/*
 * A wrapper around ioprio_set(); sets process I/O priority.
 * ioclass can be either IOPRIO_CLASS_RT, IOPRIO_CLASS_BE, IOPRIO_CLASS_IDLE
 * or 0. iodata goes from 0 to 7 depending on ioclass specified.
 */
static PyObject *
psutil_proc_ioprio_set(PyObject *self, PyObject *args) {
    long pid;
    int ioprio, ioclass, iodata;
    int retval;

    if (! PyArg_ParseTuple(args, "lii", &pid, &ioclass, &iodata))
        return NULL;
    ioprio = IOPRIO_PRIO_VALUE(ioclass, iodata);
    retval = ioprio_set(IOPRIO_WHO_PROCESS, pid, ioprio);
    if (retval == -1)
        return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}
#endif


#if PSUTIL_HAVE_PRLIMIT
/*
 * A wrapper around prlimit(2); sets process resource limits.
 * This can be used for both get and set, in which case extra
 * 'soft' and 'hard' args must be provided.
 */
static PyObject *
psutil_linux_prlimit(PyObject *self, PyObject *args) {
    long pid;
    int ret, resource;
    struct rlimit old, new;
    struct rlimit *newp = NULL;
    PyObject *py_soft = NULL;
    PyObject *py_hard = NULL;

    if (! PyArg_ParseTuple(args, "li|OO", &pid, &resource, &py_soft, &py_hard))
        return NULL;

    // get
    if (py_soft == NULL && py_hard == NULL) {
        ret = prlimit(pid, resource, NULL, &old);
        if (ret == -1)
            return PyErr_SetFromErrno(PyExc_OSError);
#if defined(PSUTIL_HAVE_LONG_LONG)
        if (sizeof(old.rlim_cur) > sizeof(long)) {
            return Py_BuildValue("LL",
                                 (PY_LONG_LONG)old.rlim_cur,
                                 (PY_LONG_LONG)old.rlim_max);
        }
#endif
        return Py_BuildValue("ll", (long)old.rlim_cur, (long)old.rlim_max);
    }

    // set
    else {
#if defined(PSUTIL_HAVE_LARGEFILE_SUPPORT)
        new.rlim_cur = PyLong_AsLongLong(py_soft);
        if (new.rlim_cur == (rlim_t) - 1 && PyErr_Occurred())
            return NULL;
        new.rlim_max = PyLong_AsLongLong(py_hard);
        if (new.rlim_max == (rlim_t) - 1 && PyErr_Occurred())
            return NULL;
#else
        new.rlim_cur = PyLong_AsLong(py_soft);
        if (new.rlim_cur == (rlim_t) - 1 && PyErr_Occurred())
            return NULL;
        new.rlim_max = PyLong_AsLong(py_hard);
        if (new.rlim_max == (rlim_t) - 1 && PyErr_Occurred())
            return NULL;
#endif
        newp = &new;
        ret = prlimit(pid, resource, newp, &old);
        if (ret == -1)
            return PyErr_SetFromErrno(PyExc_OSError);
        Py_RETURN_NONE;
    }
}
#endif


/*
 * Return disk mounted partitions as a list of tuples including device,
 * mount point and filesystem type
 */
static PyObject *
psutil_disk_partitions(PyObject *self, PyObject *args) {
    FILE *file = NULL;
    struct mntent *entry;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL)
        return NULL;

    // MOUNTED constant comes from mntent.h and it's == '/etc/mtab'
    Py_BEGIN_ALLOW_THREADS
    file = setmntent(MOUNTED, "r");
    Py_END_ALLOW_THREADS
    if ((file == 0) || (file == NULL)) {
        PyErr_SetFromErrnoWithFilename(PyExc_OSError, MOUNTED);
        goto error;
    }

    while ((entry = getmntent(file))) {
        if (entry == NULL) {
            PyErr_Format(PyExc_RuntimeError, "getmntent() syscall failed");
            goto error;
        }
        py_tuple = Py_BuildValue("(ssss)",
                                 entry->mnt_fsname,  // device
                                 entry->mnt_dir,     // mount point
                                 entry->mnt_type,    // fs type
                                 entry->mnt_opts);   // options
        if (! py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }
    endmntent(file);
    return py_retlist;

error:
    if (file != NULL)
        endmntent(file);
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    return NULL;
}


/*
 * A wrapper around sysinfo(), return system memory usage statistics.
 */
static PyObject *
psutil_linux_sysinfo(PyObject *self, PyObject *args) {
    struct sysinfo info;

    if (sysinfo(&info) != 0)
        return PyErr_SetFromErrno(PyExc_OSError);
    // note: boot time might also be determined from here
    return Py_BuildValue(
        "(kkkkkkI)",
        info.totalram,  // total
        info.freeram,  // free
        info.bufferram, // buffer
        info.sharedram, // shared
        info.totalswap, // swap tot
        info.freeswap,  // swap free
        info.mem_unit  // multiplier
    );
}


/*
 * Return process CPU affinity as a Python list
 * The dual implementation exists because of:
 * https://github.com/giampaolo/psutil/issues/536
 */

#ifdef CPU_ALLOC

static PyObject *
psutil_proc_cpu_affinity_get(PyObject *self, PyObject *args) {
    int cpu, ncpus, count, cpucount_s;
    long pid;
    size_t setsize;
    cpu_set_t *mask = NULL;
    PyObject *py_list = NULL;

    if (!PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    ncpus = NCPUS_START;
    while (1) {
        setsize = CPU_ALLOC_SIZE(ncpus);
        mask = CPU_ALLOC(ncpus);
        if (mask == NULL)
            return PyErr_NoMemory();
        if (sched_getaffinity(pid, setsize, mask) == 0)
            break;
        CPU_FREE(mask);
        if (errno != EINVAL)
            return PyErr_SetFromErrno(PyExc_OSError);
        if (ncpus > INT_MAX / 2) {
            PyErr_SetString(PyExc_OverflowError, "could not allocate "
                            "a large enough CPU set");
            return NULL;
        }
        ncpus = ncpus * 2;
    }

    py_list = PyList_New(0);
    if (py_list == NULL)
        goto error;

    cpucount_s = CPU_COUNT_S(setsize, mask);
    for (cpu = 0, count = cpucount_s; count; cpu++) {
        if (CPU_ISSET_S(cpu, setsize, mask)) {
#if PY_MAJOR_VERSION >= 3
            PyObject *cpu_num = PyLong_FromLong(cpu);
#else
            PyObject *cpu_num = PyInt_FromLong(cpu);
#endif
            if (cpu_num == NULL)
                goto error;
            if (PyList_Append(py_list, cpu_num)) {
                Py_DECREF(cpu_num);
                goto error;
            }
            Py_DECREF(cpu_num);
            --count;
        }
    }
    CPU_FREE(mask);
    return py_list;

error:
    if (mask)
        CPU_FREE(mask);
    Py_XDECREF(py_list);
    return NULL;
}
#else


/*
 * Alternative implementation in case CPU_ALLOC is not defined.
 */
static PyObject *
psutil_proc_cpu_affinity_get(PyObject *self, PyObject *args) {
    cpu_set_t cpuset;
    unsigned int len = sizeof(cpu_set_t);
    long pid;
    int i;
    PyObject* py_retlist = NULL;
    PyObject *py_cpu_num = NULL;

    if (!PyArg_ParseTuple(args, "l", &pid))
        return NULL;
	CPU_ZERO(&cpuset);
    if (sched_getaffinity(pid, len, &cpuset) < 0)
        return PyErr_SetFromErrno(PyExc_OSError);

    py_retlist = PyList_New(0);
    if (py_retlist == NULL)
        goto error;
    for (i = 0; i < CPU_SETSIZE; ++i) {
        if (CPU_ISSET(i, &cpuset)) {
            py_cpu_num = Py_BuildValue("i", i);
            if (py_cpu_num == NULL)
                goto error;
            if (PyList_Append(py_retlist, py_cpu_num))
                goto error;
            Py_DECREF(py_cpu_num);
        }
    }

    return py_retlist;

error:
    Py_XDECREF(py_cpu_num);
    Py_XDECREF(py_retlist);
    return NULL;
}
#endif

/*
 * Set process CPU affinity; expects a bitmask
 */
static PyObject *
psutil_proc_cpu_affinity_set(PyObject *self, PyObject *args) {
    cpu_set_t cpu_set;
    size_t len;
    long pid;
    int i, seq_len;
    PyObject *py_cpu_set;
    PyObject *py_cpu_seq = NULL;

    if (!PyArg_ParseTuple(args, "lO", &pid, &py_cpu_set))
        return NULL;

    if (!PySequence_Check(py_cpu_set)) {
        PyErr_Format(PyExc_TypeError, "sequence argument expected, got %s",
                     Py_TYPE(py_cpu_set)->tp_name);
        goto error;
    }

    py_cpu_seq = PySequence_Fast(py_cpu_set, "expected a sequence or integer");
    if (!py_cpu_seq)
        goto error;
    seq_len = PySequence_Fast_GET_SIZE(py_cpu_seq);
    CPU_ZERO(&cpu_set);
    for (i = 0; i < seq_len; i++) {
        PyObject *item = PySequence_Fast_GET_ITEM(py_cpu_seq, i);
#if PY_MAJOR_VERSION >= 3
        long value = PyLong_AsLong(item);
#else
        long value = PyInt_AsLong(item);
#endif
        if ((value == -1) || PyErr_Occurred()) {
            if (!PyErr_Occurred())
                PyErr_SetString(PyExc_ValueError, "invalid CPU value");
            goto error;
        }
        CPU_SET(value, &cpu_set);
    }


    len = sizeof(cpu_set);
    if (sched_setaffinity(pid, len, &cpu_set)) {
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


/*
 * Return currently connected users as a list of tuples.
 */
static PyObject *
psutil_users(PyObject *self, PyObject *args) {
    struct utmp *ut;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_user_proc = NULL;

    if (py_retlist == NULL)
        return NULL;
    setutent();
    while (NULL != (ut = getutent())) {
        py_tuple = NULL;
        py_user_proc = NULL;
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
            py_user_proc              // (bool) user process
        );
        if (! py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }
    endutent();
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_user_proc);
    Py_DECREF(py_retlist);
    endutent();
    return NULL;
}


/*
 * Return stats about a particular network
 * interface.  References:
 * https://github.com/dpaleino/wicd/blob/master/wicd/backends/be-ioctl.py
 * http://www.i-scream.org/libstatgrab/
 */
static PyObject*
psutil_net_if_duplex_speed(PyObject* self, PyObject* args) {
    char *nic_name;
    int sock = 0;
    int ret;
    int duplex;
    int speed;
    struct ifreq ifr;
    struct ethtool_cmd ethcmd;
    PyObject *py_retlist = NULL;

    if (! PyArg_ParseTuple(args, "s", &nic_name))
        return NULL;

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == -1)
        goto error;
    strncpy(ifr.ifr_name, nic_name, sizeof(ifr.ifr_name));

    // duplex and speed
    memset(&ethcmd, 0, sizeof ethcmd);
    ethcmd.cmd = ETHTOOL_GSET;
    ifr.ifr_data = (void *)&ethcmd;
    ret = ioctl(sock, SIOCETHTOOL, &ifr);

    if (ret != -1) {
        duplex = ethcmd.duplex;
        speed = ethcmd.speed;
    }
    else {
        if ((errno == EOPNOTSUPP) || (errno == EINVAL)) {
            // EOPNOTSUPP may occur in case of wi-fi cards.
            // For EINVAL see:
            // https://github.com/giampaolo/psutil/issues/797
            //     #issuecomment-202999532
            duplex = DUPLEX_UNKNOWN;
            speed = 0;
        }
        else {
            goto error;
        }
    }

    close(sock);
    py_retlist = Py_BuildValue("[ii]", duplex, speed);
    if (!py_retlist)
        goto error;
    return py_retlist;

error:
    if (sock != -1)
        close(sock);
    PyErr_SetFromErrno(PyExc_OSError);
    return NULL;
}


/*
 * Define the psutil C module methods and initialize the module.
 */
static PyMethodDef
PsutilMethods[] = {

    // --- per-process functions

#if PSUTIL_HAVE_IOPRIO
    {"proc_ioprio_get", psutil_proc_ioprio_get, METH_VARARGS,
     "Get process I/O priority"},
    {"proc_ioprio_set", psutil_proc_ioprio_set, METH_VARARGS,
     "Set process I/O priority"},
#endif
    {"proc_cpu_affinity_get", psutil_proc_cpu_affinity_get, METH_VARARGS,
     "Return process CPU affinity as a Python long (the bitmask)."},
    {"proc_cpu_affinity_set", psutil_proc_cpu_affinity_set, METH_VARARGS,
     "Set process CPU affinity; expects a bitmask."},

    // --- system related functions

    {"disk_partitions", psutil_disk_partitions, METH_VARARGS,
     "Return disk mounted partitions as a list of tuples including "
     "device, mount point and filesystem type"},
    {"users", psutil_users, METH_VARARGS,
     "Return currently connected users as a list of tuples"},
    {"net_if_duplex_speed", psutil_net_if_duplex_speed, METH_VARARGS,
     "Return duplex and speed info about a NIC"},

    // --- linux specific

    {"linux_sysinfo", psutil_linux_sysinfo, METH_VARARGS,
     "A wrapper around sysinfo(), return system memory usage statistics"},
#if PSUTIL_HAVE_PRLIMIT
    {"linux_prlimit", psutil_linux_prlimit, METH_VARARGS,
     "Get or set process resource limits."},
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
psutil_linux_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int
psutil_linux_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef
        moduledef = {
    PyModuleDef_HEAD_INIT,
    "psutil_linux",
    NULL,
    sizeof(struct module_state),
    PsutilMethods,
    NULL,
    psutil_linux_traverse,
    psutil_linux_clear,
    NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit__psutil_linux(void)

#else
#define INITERROR return

void init_psutil_linux(void)
#endif
{
    PyObject *v;
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("_psutil_linux", PsutilMethods);
#endif

    PyModule_AddIntConstant(module, "version", PSUTIL_VERSION);
#if PSUTIL_HAVE_PRLIMIT
    PyModule_AddIntConstant(module, "RLIMIT_AS", RLIMIT_AS);
    PyModule_AddIntConstant(module, "RLIMIT_CORE", RLIMIT_CORE);
    PyModule_AddIntConstant(module, "RLIMIT_CPU", RLIMIT_CPU);
    PyModule_AddIntConstant(module, "RLIMIT_DATA", RLIMIT_DATA);
    PyModule_AddIntConstant(module, "RLIMIT_FSIZE", RLIMIT_FSIZE);
    PyModule_AddIntConstant(module, "RLIMIT_LOCKS", RLIMIT_LOCKS);
    PyModule_AddIntConstant(module, "RLIMIT_MEMLOCK", RLIMIT_MEMLOCK);
    PyModule_AddIntConstant(module, "RLIMIT_NOFILE", RLIMIT_NOFILE);
    PyModule_AddIntConstant(module, "RLIMIT_NPROC", RLIMIT_NPROC);
    PyModule_AddIntConstant(module, "RLIMIT_RSS", RLIMIT_RSS);
    PyModule_AddIntConstant(module, "RLIMIT_STACK", RLIMIT_STACK);

#if defined(HAVE_LONG_LONG)
    if (sizeof(RLIM_INFINITY) > sizeof(long)) {
        v = PyLong_FromLongLong((PY_LONG_LONG) RLIM_INFINITY);
    } else
#endif
    {
        v = PyLong_FromLong((long) RLIM_INFINITY);
    }
    if (v) {
        PyModule_AddObject(module, "RLIM_INFINITY", v);
    }

#ifdef RLIMIT_MSGQUEUE
    PyModule_AddIntConstant(module, "RLIMIT_MSGQUEUE", RLIMIT_MSGQUEUE);
#endif
#ifdef RLIMIT_NICE
    PyModule_AddIntConstant(module, "RLIMIT_NICE", RLIMIT_NICE);
#endif
#ifdef RLIMIT_RTPRIO
    PyModule_AddIntConstant(module, "RLIMIT_RTPRIO", RLIMIT_RTPRIO);
#endif
#ifdef RLIMIT_RTTIME
    PyModule_AddIntConstant(module, "RLIMIT_RTTIME", RLIMIT_RTTIME);
#endif
#ifdef RLIMIT_SIGPENDING
    PyModule_AddIntConstant(module, "RLIMIT_SIGPENDING", RLIMIT_SIGPENDING);
#endif
#endif
    PyModule_AddIntConstant(module, "DUPLEX_HALF", DUPLEX_HALF);
    PyModule_AddIntConstant(module, "DUPLEX_FULL", DUPLEX_FULL);
    PyModule_AddIntConstant(module, "DUPLEX_UNKNOWN", DUPLEX_UNKNOWN);

    if (module == NULL)
        INITERROR;
#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
