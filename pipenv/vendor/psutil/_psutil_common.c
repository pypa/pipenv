/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Routines common to all platforms.
 */

#ifdef PSUTIL_POSIX
#include <sys/types.h>
#include <signal.h>
#endif

#include <Python.h>


/*
 * Set OSError(errno=ESRCH, strerror="No such process") Python exception.
 */
PyObject *
NoSuchProcess(void) {
    PyObject *exc;
    char *msg = strerror(ESRCH);
    exc = PyObject_CallFunction(PyExc_OSError, "(is)", ESRCH, msg);
    PyErr_SetObject(PyExc_OSError, exc);
    Py_XDECREF(exc);
    return NULL;
}


/*
 * Set OSError(errno=EACCES, strerror="Permission denied") Python exception.
 */
PyObject *
AccessDenied(void) {
    PyObject *exc;
    char *msg = strerror(EACCES);
    exc = PyObject_CallFunction(PyExc_OSError, "(is)", EACCES, msg);
    PyErr_SetObject(PyExc_OSError, exc);
    Py_XDECREF(exc);
    return NULL;
}


#ifdef PSUTIL_POSIX
/*
 * Check if PID exists. Return values:
 * 1: exists
 * 0: does not exist
 * -1: error (Python exception is set)
 */
int
psutil_pid_exists(long pid) {
    int ret;

    // No negative PID exists, plus -1 is an alias for sending signal
    // too all processes except system ones. Not what we want.
    if (pid < 0)
        return 0;

    // As per "man 2 kill" PID 0 is an alias for sending the signal to
    // every process in the process group of the calling process.
    // Not what we want. Some platforms have PID 0, some do not.
    // We decide that at runtime.
    if (pid == 0) {
#if defined(PSUTIL_LINUX) || defined(PSUTIL_FREEBSD)
        return 0;
#else
        return 1;
#endif
    }

#if defined(PSUTIL_OSX)
    ret = kill((pid_t)pid , 0);
#else
    ret = kill(pid , 0);
#endif

    if (ret == 0)
        return 1;
    else {
        if (errno == ESRCH) {
            // ESRCH == No such process
            return 0;
        }
        else if (errno == EPERM) {
            // EPERM clearly indicates there's a process to deny
            // access to.
            return 1;
        }
        else {
            // According to "man 2 kill" possible error values are
            // (EINVAL, EPERM, ESRCH) therefore we should never get
            // here. If we do let's be explicit in considering this
            // an error.
            PyErr_SetFromErrno(PyExc_OSError);
            return -1;
        }
    }
}


/*
 * Utility used for those syscalls which do not return a meaningful
 * error that we can translate into an exception which makes sense.
 * As such, we'll have to guess.
 * On UNIX, if errno is set, we return that one (OSError).
 * Else, if PID does not exist we assume the syscall failed because
 * of that so we raise NoSuchProcess.
 * If none of this is true we giveup and raise RuntimeError(msg).
 * This will always set a Python exception and return NULL.
 */
int
psutil_raise_for_pid(long pid, char *msg) {
    // Set exception to AccessDenied if pid exists else NoSuchProcess.
    if (errno != 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return 0;
    }
    if (psutil_pid_exists(pid) == 0)
        NoSuchProcess();
    else
        PyErr_SetString(PyExc_RuntimeError, msg);
    return 0;
}
#endif
