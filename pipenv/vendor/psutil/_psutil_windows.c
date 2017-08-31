/*
 * Copyright (c) 2009, Jay Loden, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Windows platform-specific module methods for _psutil_windows
 */

// Fixes clash between winsock2.h and windows.h
#define WIN32_LEAN_AND_MEAN

#include <Python.h>
#include <windows.h>
#include <Psapi.h>
#include <time.h>
#include <lm.h>
#include <WinIoCtl.h>
#include <tchar.h>
#include <tlhelp32.h>
#include <winsock2.h>
#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
#include <ws2tcpip.h>
#endif
#include <iphlpapi.h>
#include <wtsapi32.h>
#include <Winsvc.h>
#include <PowrProf.h>

// Link with Iphlpapi.lib
#pragma comment(lib, "IPHLPAPI.lib")

#include "_psutil_common.h"
#include "arch/windows/security.h"
#include "arch/windows/process_info.h"
#include "arch/windows/process_handles.h"
#include "arch/windows/ntextapi.h"
#include "arch/windows/inet_ntop.h"
#include "arch/windows/services.h"

#ifdef __MINGW32__
#include "arch/windows/glpi.h"
#endif


/*
 * ============================================================================
 * Utilities
 * ============================================================================
 */

 // a flag for connections without an actual status
static int PSUTIL_CONN_NONE = 128;

#define MALLOC(x) HeapAlloc(GetProcessHeap(), 0, (x))
#define FREE(x) HeapFree(GetProcessHeap(), 0, (x))
#define LO_T ((float)1e-7)
#define HI_T (LO_T*4294967296.0)
#define BYTESWAP_USHORT(x) ((((USHORT)(x) << 8) | ((USHORT)(x) >> 8)) & 0xffff)
#ifndef AF_INET6
#define AF_INET6 23
#endif
#define _psutil_conn_decref_objs() \
    Py_DECREF(_AF_INET); \
    Py_DECREF(_AF_INET6);\
    Py_DECREF(_SOCK_STREAM);\
    Py_DECREF(_SOCK_DGRAM);

typedef BOOL (WINAPI *LPFN_GLPI)
    (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION,  PDWORD);

// fix for mingw32, see
// https://github.com/giampaolo/psutil/issues/351#c2
typedef struct _DISK_PERFORMANCE_WIN_2008 {
    LARGE_INTEGER BytesRead;
    LARGE_INTEGER BytesWritten;
    LARGE_INTEGER ReadTime;
    LARGE_INTEGER WriteTime;
    LARGE_INTEGER IdleTime;
    DWORD         ReadCount;
    DWORD         WriteCount;
    DWORD         QueueDepth;
    DWORD         SplitCount;
    LARGE_INTEGER QueryTime;
    DWORD         StorageDeviceNumber;
    WCHAR         StorageManagerName[8];
} DISK_PERFORMANCE_WIN_2008;

// --- network connections mingw32 support
#ifndef _IPRTRMIB_H
#if (_WIN32_WINNT < 0x0600) // Windows XP
typedef struct _MIB_TCP6ROW_OWNER_PID {
    UCHAR ucLocalAddr[16];
    DWORD dwLocalScopeId;
    DWORD dwLocalPort;
    UCHAR ucRemoteAddr[16];
    DWORD dwRemoteScopeId;
    DWORD dwRemotePort;
    DWORD dwState;
    DWORD dwOwningPid;
} MIB_TCP6ROW_OWNER_PID, *PMIB_TCP6ROW_OWNER_PID;

typedef struct _MIB_TCP6TABLE_OWNER_PID {
    DWORD dwNumEntries;
    MIB_TCP6ROW_OWNER_PID table[ANY_SIZE];
} MIB_TCP6TABLE_OWNER_PID, *PMIB_TCP6TABLE_OWNER_PID;
#endif
#endif

#ifndef __IPHLPAPI_H__
typedef struct in6_addr {
    union {
        UCHAR Byte[16];
        USHORT Word[8];
    } u;
} IN6_ADDR, *PIN6_ADDR, FAR *LPIN6_ADDR;

typedef enum _UDP_TABLE_CLASS {
    UDP_TABLE_BASIC,
    UDP_TABLE_OWNER_PID,
    UDP_TABLE_OWNER_MODULE
} UDP_TABLE_CLASS, *PUDP_TABLE_CLASS;

typedef struct _MIB_UDPROW_OWNER_PID {
    DWORD dwLocalAddr;
    DWORD dwLocalPort;
    DWORD dwOwningPid;
} MIB_UDPROW_OWNER_PID, *PMIB_UDPROW_OWNER_PID;

typedef struct _MIB_UDPTABLE_OWNER_PID {
    DWORD dwNumEntries;
    MIB_UDPROW_OWNER_PID table[ANY_SIZE];
} MIB_UDPTABLE_OWNER_PID, *PMIB_UDPTABLE_OWNER_PID;
#endif

#if (_WIN32_WINNT < 0x0600) // Windows XP
typedef struct _MIB_UDP6ROW_OWNER_PID {
    UCHAR ucLocalAddr[16];
    DWORD dwLocalScopeId;
    DWORD dwLocalPort;
    DWORD dwOwningPid;
} MIB_UDP6ROW_OWNER_PID, *PMIB_UDP6ROW_OWNER_PID;

typedef struct _MIB_UDP6TABLE_OWNER_PID {
    DWORD dwNumEntries;
    MIB_UDP6ROW_OWNER_PID table[ANY_SIZE];
} MIB_UDP6TABLE_OWNER_PID, *PMIB_UDP6TABLE_OWNER_PID;
#endif

typedef struct _PROCESSOR_POWER_INFORMATION {
   ULONG Number;
   ULONG MaxMhz;
   ULONG CurrentMhz;
   ULONG MhzLimit;
   ULONG MaxIdleState;
   ULONG CurrentIdleState;
} PROCESSOR_POWER_INFORMATION, *PPROCESSOR_POWER_INFORMATION;


PIP_ADAPTER_ADDRESSES
psutil_get_nic_addresses() {
    // allocate a 15 KB buffer to start with
    int outBufLen = 15000;
    DWORD dwRetVal = 0;
    ULONG attempts = 0;
    PIP_ADAPTER_ADDRESSES pAddresses = NULL;

    do {
        pAddresses = (IP_ADAPTER_ADDRESSES *) malloc(outBufLen);
        if (pAddresses == NULL) {
            PyErr_NoMemory();
            return NULL;
        }

        dwRetVal = GetAdaptersAddresses(AF_UNSPEC, 0, NULL, pAddresses,
                                        &outBufLen);
        if (dwRetVal == ERROR_BUFFER_OVERFLOW) {
            free(pAddresses);
            pAddresses = NULL;
        }
        else {
            break;
        }

        attempts++;
    } while ((dwRetVal == ERROR_BUFFER_OVERFLOW) && (attempts < 3));

    if (dwRetVal != NO_ERROR) {
        PyErr_SetString(
            PyExc_RuntimeError, "GetAdaptersAddresses() syscall failed.");
        return NULL;
    }

    return pAddresses;
}


/*
 * ============================================================================
 * Public Python API
 * ============================================================================
 */


static ULONGLONG (*psutil_GetTickCount64)(void) = NULL;

/*
 * Return a Python float representing the system uptime expressed in seconds
 * since the epoch.
 */
static PyObject *
psutil_boot_time(PyObject *self, PyObject *args) {
#if (_WIN32_WINNT >= 0x0600)  // Windows Vista
    ULONGLONG uptime;
#else
    double uptime;
#endif
    time_t pt;
    FILETIME fileTime;
    long long ll;
    HINSTANCE hKernel32;
    psutil_GetTickCount64 = NULL;

    GetSystemTimeAsFileTime(&fileTime);

    /*
    HUGE thanks to:
    http://johnstewien.spaces.live.com/blog/cns!E6885DB5CEBABBC8!831.entry

    This function converts the FILETIME structure to the 32 bit
    Unix time structure.
    The time_t is a 32-bit value for the number of seconds since
    January 1, 1970. A FILETIME is a 64-bit for the number of
    100-nanosecond periods since January 1, 1601. Convert by
    subtracting the number of 100-nanosecond period betwee 01-01-1970
    and 01-01-1601, from time_t the divide by 1e+7 to get to the same
    base granularity.
    */
    ll = (((LONGLONG)(fileTime.dwHighDateTime)) << 32) \
        + fileTime.dwLowDateTime;
    pt = (time_t)((ll - 116444736000000000ull) / 10000000ull);

    // GetTickCount64() is Windows Vista+ only. Dinamically load
    // GetTickCount64() at runtime. We may have used
    // "#if (_WIN32_WINNT >= 0x0600)" pre-processor but that way
    // the produced exe/wheels cannot be used on Windows XP, see:
    // https://github.com/giampaolo/psutil/issues/811#issuecomment-230639178
    hKernel32 = GetModuleHandleW(L"KERNEL32");
    psutil_GetTickCount64 = (void*)GetProcAddress(hKernel32, "GetTickCount64");
    if (psutil_GetTickCount64 != NULL) {
        // Windows >= Vista
        uptime = psutil_GetTickCount64() / (ULONGLONG)1000.00f;
    }
    else {
        // Windows XP.
        // GetTickCount() time will wrap around to zero if the
        // system is run continuously for 49.7 days.
        uptime = GetTickCount() / 1000.00f;
    }

    return Py_BuildValue("d", (double)pt - (double)uptime);
}


/*
 * Return 1 if PID exists in the current process list, else 0.
 */
static PyObject *
psutil_pid_exists(PyObject *self, PyObject *args) {
    long pid;
    int status;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    status = psutil_pid_is_running(pid);
    if (-1 == status)
        return NULL; // exception raised in psutil_pid_is_running()
    return PyBool_FromLong(status);
}


/*
 * Return a Python list of all the PIDs running on the system.
 */
static PyObject *
psutil_pids(PyObject *self, PyObject *args) {
    DWORD *proclist = NULL;
    DWORD numberOfReturnedPIDs;
    DWORD i;
    PyObject *py_pid = NULL;
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;
    proclist = psutil_get_pids(&numberOfReturnedPIDs);
    if (proclist == NULL)
        goto error;

    for (i = 0; i < numberOfReturnedPIDs; i++) {
        py_pid = Py_BuildValue("I", proclist[i]);
        if (!py_pid)
            goto error;
        if (PyList_Append(py_retlist, py_pid))
            goto error;
        Py_DECREF(py_pid);
    }

    // free C array allocated for PIDs
    free(proclist);
    return py_retlist;

error:
    Py_XDECREF(py_pid);
    Py_DECREF(py_retlist);
    if (proclist != NULL)
        free(proclist);
    return NULL;
}


/*
 * Kill a process given its PID.
 */
static PyObject *
psutil_proc_kill(PyObject *self, PyObject *args) {
    HANDLE hProcess;
    long pid;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (pid == 0)
        return AccessDenied();

    hProcess = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
    if (hProcess == NULL) {
        if (GetLastError() == ERROR_INVALID_PARAMETER) {
            // see https://github.com/giampaolo/psutil/issues/24
            NoSuchProcess();
        }
        else {
            PyErr_SetFromWindowsErr(0);
        }
        return NULL;
    }

    // kill the process
    if (! TerminateProcess(hProcess, 0)) {
        PyErr_SetFromWindowsErr(0);
        CloseHandle(hProcess);
        return NULL;
    }

    CloseHandle(hProcess);
    Py_RETURN_NONE;
}


/*
 * Wait for process to terminate and return its exit code.
 */
static PyObject *
psutil_proc_wait(PyObject *self, PyObject *args) {
    HANDLE hProcess;
    DWORD ExitCode;
    DWORD retVal;
    long pid;
    long timeout;

    if (! PyArg_ParseTuple(args, "ll", &pid, &timeout))
        return NULL;
    if (pid == 0)
        return AccessDenied();

    hProcess = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_INFORMATION,
                           FALSE, pid);
    if (hProcess == NULL) {
        if (GetLastError() == ERROR_INVALID_PARAMETER) {
            // no such process; we do not want to raise NSP but
            // return None instead.
            Py_RETURN_NONE;
        }
        else {
            PyErr_SetFromWindowsErr(0);
            return NULL;
        }
    }

    // wait until the process has terminated
    Py_BEGIN_ALLOW_THREADS
    retVal = WaitForSingleObject(hProcess, timeout);
    Py_END_ALLOW_THREADS

    if (retVal == WAIT_FAILED) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(GetLastError());
    }
    if (retVal == WAIT_TIMEOUT) {
        CloseHandle(hProcess);
        return Py_BuildValue("l", WAIT_TIMEOUT);
    }

    // get the exit code; note: subprocess module (erroneously?) uses
    // what returned by WaitForSingleObject
    if (GetExitCodeProcess(hProcess, &ExitCode) == 0) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(GetLastError());
    }
    CloseHandle(hProcess);
#if PY_MAJOR_VERSION >= 3
    return PyLong_FromLong((long) ExitCode);
#else
    return PyInt_FromLong((long) ExitCode);
#endif
}


/*
 * Return a Python tuple (user_time, kernel_time)
 */
static PyObject *
psutil_proc_cpu_times(PyObject *self, PyObject *args) {
    long        pid;
    HANDLE      hProcess;
    FILETIME    ftCreate, ftExit, ftKernel, ftUser;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL)
        return NULL;
    if (! GetProcessTimes(hProcess, &ftCreate, &ftExit, &ftKernel, &ftUser)) {
        CloseHandle(hProcess);
        if (GetLastError() == ERROR_ACCESS_DENIED) {
            // usually means the process has died so we throw a NoSuchProcess
            // here
            return NoSuchProcess();
        }
        else {
            PyErr_SetFromWindowsErr(0);
            return NULL;
        }
    }

    CloseHandle(hProcess);

    /*
     * User and kernel times are represented as a FILETIME structure
     * wich contains a 64-bit value representing the number of
     * 100-nanosecond intervals since January 1, 1601 (UTC):
     * http://msdn.microsoft.com/en-us/library/ms724284(VS.85).aspx
     * To convert it into a float representing the seconds that the
     * process has executed in user/kernel mode I borrowed the code
     * below from Python's Modules/posixmodule.c
     */
    return Py_BuildValue(
       "(dd)",
       (double)(ftUser.dwHighDateTime * 429.4967296 + \
                ftUser.dwLowDateTime * 1e-7),
       (double)(ftKernel.dwHighDateTime * 429.4967296 + \
                ftKernel.dwLowDateTime * 1e-7)
   );
}


/*
 * Return a Python float indicating the process create time expressed in
 * seconds since the epoch.
 */
static PyObject *
psutil_proc_create_time(PyObject *self, PyObject *args) {
    long        pid;
    long long   unix_time;
    DWORD       exitCode;
    HANDLE      hProcess;
    BOOL        ret;
    FILETIME    ftCreate, ftExit, ftKernel, ftUser;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    // special case for PIDs 0 and 4, return system boot time
    if (0 == pid || 4 == pid)
        return psutil_boot_time(NULL, NULL);

    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL)
        return NULL;
    if (! GetProcessTimes(hProcess, &ftCreate, &ftExit, &ftKernel, &ftUser)) {
        CloseHandle(hProcess);
        if (GetLastError() == ERROR_ACCESS_DENIED) {
            // usually means the process has died so we throw a
            // NoSuchProcess here
            return NoSuchProcess();
        }
        else {
            PyErr_SetFromWindowsErr(0);
            return NULL;
        }
    }

    // Make sure the process is not gone as OpenProcess alone seems to be
    // unreliable in doing so (it seems a previous call to p.wait() makes
    // it unreliable).
    // This check is important as creation time is used to make sure the
    // process is still running.
    ret = GetExitCodeProcess(hProcess, &exitCode);
    CloseHandle(hProcess);
    if (ret != 0) {
        if (exitCode != STILL_ACTIVE)
            return NoSuchProcess();
    }
    else {
        // Ignore access denied as it means the process is still alive.
        // For all other errors, we want an exception.
        if (GetLastError() != ERROR_ACCESS_DENIED) {
            PyErr_SetFromWindowsErr(0);
            return NULL;
        }
    }

    /*
    Convert the FILETIME structure to a Unix time.
    It's the best I could find by googling and borrowing code here and there.
    The time returned has a precision of 1 second.
    */
    unix_time = ((LONGLONG)ftCreate.dwHighDateTime) << 32;
    unix_time += ftCreate.dwLowDateTime - 116444736000000000LL;
    unix_time /= 10000000;
    return Py_BuildValue("d", (double)unix_time);
}



/*
 * Return the number of logical CPUs.
 */
static PyObject *
psutil_cpu_count_logical(PyObject *self, PyObject *args) {
    SYSTEM_INFO system_info;
    system_info.dwNumberOfProcessors = 0;

    GetSystemInfo(&system_info);
    if (system_info.dwNumberOfProcessors == 0)
        Py_RETURN_NONE;  // mimic os.cpu_count()
    else
        return Py_BuildValue("I", system_info.dwNumberOfProcessors);
}


/*
 * Return the number of physical CPU cores.
 */
static PyObject *
psutil_cpu_count_phys(PyObject *self, PyObject *args) {
    LPFN_GLPI glpi;
    DWORD rc;
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION buffer = NULL;
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION ptr = NULL;
    DWORD length = 0;
    DWORD offset = 0;
    int ncpus = 0;

    glpi = (LPFN_GLPI)GetProcAddress(GetModuleHandle(TEXT("kernel32")),
                                     "GetLogicalProcessorInformation");
    if (glpi == NULL)
        goto return_none;

    while (1) {
        rc = glpi(buffer, &length);
        if (rc == FALSE) {
            if (GetLastError() == ERROR_INSUFFICIENT_BUFFER) {
                if (buffer)
                    free(buffer);
                buffer = (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION)malloc(
                    length);
                if (NULL == buffer) {
                    PyErr_NoMemory();
                    return NULL;
                }
            }
            else {
                goto return_none;
            }
        }
        else {
            break;
        }
    }

    ptr = buffer;
    while (offset + sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION) <= length) {
        if (ptr->Relationship == RelationProcessorCore)
            ncpus += 1;
        offset += sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION);
        ptr++;
    }

    free(buffer);
    if (ncpus == 0)
        goto return_none;
    else
        return Py_BuildValue("i", ncpus);

return_none:
    // mimic os.cpu_count()
    if (buffer != NULL)
        free(buffer);
    Py_RETURN_NONE;
}


/*
 * Return process cmdline as a Python list of cmdline arguments.
 */
static PyObject *
psutil_proc_cmdline(PyObject *self, PyObject *args) {
    long pid;
    int pid_return;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if ((pid == 0) || (pid == 4))
        return Py_BuildValue("[]");

    pid_return = psutil_pid_is_running(pid);
    if (pid_return == 0)
        return NoSuchProcess();
    if (pid_return == -1)
        return NULL;

    return psutil_get_cmdline(pid);
}


/*
 * Return process cmdline as a Python list of cmdline arguments.
 */
static PyObject *
psutil_proc_environ(PyObject *self, PyObject *args) {
    long pid;
    int pid_return;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if ((pid == 0) || (pid == 4))
        return Py_BuildValue("s", "");

    pid_return = psutil_pid_is_running(pid);
    if (pid_return == 0)
        return NoSuchProcess();
    if (pid_return == -1)
        return NULL;

    return psutil_get_environ(pid);
}


/*
 * Return process executable path.
 */
static PyObject *
psutil_proc_exe(PyObject *self, PyObject *args) {
    long pid;
    HANDLE hProcess;
    wchar_t exe[MAX_PATH];

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid_waccess(pid, PROCESS_QUERY_INFORMATION);
    if (NULL == hProcess)
        return NULL;
    if (GetProcessImageFileNameW(hProcess, exe, MAX_PATH) == 0) {
        CloseHandle(hProcess);
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    CloseHandle(hProcess);
    return Py_BuildValue("u", exe);
}


/*
 * Return process base name.
 * Note: psutil_proc_exe() is attempted first because it's faster
 * but it raise AccessDenied for processes owned by other users
 * in which case we fall back on using this.
 */
static PyObject *
psutil_proc_name(PyObject *self, PyObject *args) {
    long pid;
    int ok;
    PROCESSENTRY32W pentry;
    HANDLE hSnapShot;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hSnapShot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, pid);
    if (hSnapShot == INVALID_HANDLE_VALUE) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    pentry.dwSize = sizeof(PROCESSENTRY32W);
    ok = Process32FirstW(hSnapShot, &pentry);
    if (! ok) {
        CloseHandle(hSnapShot);
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    while (ok) {
        if (pentry.th32ProcessID == pid) {
            CloseHandle(hSnapShot);
            return PyUnicode_FromWideChar(
                pentry.szExeFile, wcslen(pentry.szExeFile));
        }
        ok = Process32NextW(hSnapShot, &pentry);
    }

    CloseHandle(hSnapShot);
    NoSuchProcess();
    return NULL;
}


/*
 * Return process memory information as a Python tuple.
 */
static PyObject *
psutil_proc_memory_info(PyObject *self, PyObject *args) {
    HANDLE hProcess;
    DWORD pid;
#if (_WIN32_WINNT >= 0x0501)  // Windows XP with SP2
    PROCESS_MEMORY_COUNTERS_EX cnt;
#else
    PROCESS_MEMORY_COUNTERS cnt;
#endif
    SIZE_T private = 0;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    hProcess = psutil_handle_from_pid(pid);
    if (NULL == hProcess)
        return NULL;

    if (! GetProcessMemoryInfo(hProcess, (PPROCESS_MEMORY_COUNTERS)&cnt,
                               sizeof(cnt))) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(0);
    }

#if (_WIN32_WINNT >= 0x0501)  // Windows XP with SP2
    private = cnt.PrivateUsage;
#endif

    CloseHandle(hProcess);

    // PROCESS_MEMORY_COUNTERS values are defined as SIZE_T which on 64bits
    // is an (unsigned long long) and on 32bits is an (unsigned int).
    // "_WIN64" is defined if we're running a 64bit Python interpreter not
    // exclusively if the *system* is 64bit.
#if defined(_WIN64)
    return Py_BuildValue(
        "(kKKKKKKKKK)",
        cnt.PageFaultCount,  // unsigned long
        (unsigned long long)cnt.PeakWorkingSetSize,
        (unsigned long long)cnt.WorkingSetSize,
        (unsigned long long)cnt.QuotaPeakPagedPoolUsage,
        (unsigned long long)cnt.QuotaPagedPoolUsage,
        (unsigned long long)cnt.QuotaPeakNonPagedPoolUsage,
        (unsigned long long)cnt.QuotaNonPagedPoolUsage,
        (unsigned long long)cnt.PagefileUsage,
        (unsigned long long)cnt.PeakPagefileUsage,
        (unsigned long long)private);
#else
    return Py_BuildValue(
        "(kIIIIIIIII)",
        cnt.PageFaultCount,    // unsigned long
        (unsigned int)cnt.PeakWorkingSetSize,
        (unsigned int)cnt.WorkingSetSize,
        (unsigned int)cnt.QuotaPeakPagedPoolUsage,
        (unsigned int)cnt.QuotaPagedPoolUsage,
        (unsigned int)cnt.QuotaPeakNonPagedPoolUsage,
        (unsigned int)cnt.QuotaNonPagedPoolUsage,
        (unsigned int)cnt.PagefileUsage,
        (unsigned int)cnt.PeakPagefileUsage,
        (unsigned int)private);
#endif
}



/**
 * Returns the USS of the process.
 * Reference:
 * https://dxr.mozilla.org/mozilla-central/source/xpcom/base/
 *     nsMemoryReporterManager.cpp
 */
static PyObject *
psutil_proc_memory_uss(PyObject *self, PyObject *args)
{
    DWORD pid;
    HANDLE proc;
    PSAPI_WORKING_SET_INFORMATION tmp;
    DWORD tmp_size = sizeof(tmp);
    size_t entries;
    size_t private_pages;
    size_t i;
    DWORD info_array_size;
    PSAPI_WORKING_SET_INFORMATION* info_array;
    SYSTEM_INFO system_info;
    PyObject* py_result = NULL;
    unsigned long long total = 0;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    proc = psutil_handle_from_pid(pid);
    if (proc == NULL)
        return NULL;

    // Determine how many entries we need.
    memset(&tmp, 0, tmp_size);
    if (!QueryWorkingSet(proc, &tmp, tmp_size)) {
        // NB: QueryWorkingSet is expected to fail here due to the
        // buffer being too small.
        if (tmp.NumberOfEntries == 0) {
            PyErr_SetFromWindowsErr(0);
            goto done;
        }
    }

    // Fudge the size in case new entries are added between calls.
    entries = tmp.NumberOfEntries * 2;

    if (!entries) {
        goto done;
    }

    info_array_size = tmp_size + (entries * sizeof(PSAPI_WORKING_SET_BLOCK));
    info_array = (PSAPI_WORKING_SET_INFORMATION*)malloc(info_array_size);
    if (!info_array) {
        PyErr_NoMemory();
        goto done;
    }

    if (!QueryWorkingSet(proc, info_array, info_array_size)) {
        PyErr_SetFromWindowsErr(0);
        goto done;
    }

    entries = (size_t)info_array->NumberOfEntries;
    private_pages = 0;
    for (i = 0; i < entries; i++) {
        // Count shared pages that only one process is using as private.
        if (!info_array->WorkingSetInfo[i].Shared ||
                info_array->WorkingSetInfo[i].ShareCount <= 1) {
            private_pages++;
        }
    }

    // GetSystemInfo has no return value.
    GetSystemInfo(&system_info);
    total = private_pages * system_info.dwPageSize;
    py_result = Py_BuildValue("K", total);

done:
    if (proc) {
        CloseHandle(proc);
    }

    if (info_array) {
        free(info_array);
    }

    return py_result;
}


/*
 * Return a Python integer indicating the total amount of physical memory
 * in bytes.
 */
static PyObject *
psutil_virtual_mem(PyObject *self, PyObject *args) {
    MEMORYSTATUSEX memInfo;
    memInfo.dwLength = sizeof(MEMORYSTATUSEX);

    if (! GlobalMemoryStatusEx(&memInfo))
        return PyErr_SetFromWindowsErr(0);
    return Py_BuildValue("(LLLLLL)",
                         memInfo.ullTotalPhys,      // total
                         memInfo.ullAvailPhys,      // avail
                         memInfo.ullTotalPageFile,  // total page file
                         memInfo.ullAvailPageFile,  // avail page file
                         memInfo.ullTotalVirtual,   // total virtual
                         memInfo.ullAvailVirtual);  // avail virtual
}


/*
 * Retrieves system CPU timing information as a (user, system, idle)
 * tuple. On a multiprocessor system, the values returned are the
 * sum of the designated times across all processors.
 */
static PyObject *
psutil_cpu_times(PyObject *self, PyObject *args) {
    float idle, kernel, user, system;
    FILETIME idle_time, kernel_time, user_time;

    if (!GetSystemTimes(&idle_time, &kernel_time, &user_time))
        return PyErr_SetFromWindowsErr(0);

    idle = (float)((HI_T * idle_time.dwHighDateTime) + \
                   (LO_T * idle_time.dwLowDateTime));
    user = (float)((HI_T * user_time.dwHighDateTime) + \
                   (LO_T * user_time.dwLowDateTime));
    kernel = (float)((HI_T * kernel_time.dwHighDateTime) + \
                     (LO_T * kernel_time.dwLowDateTime));

    // Kernel time includes idle time.
    // We return only busy kernel time subtracting idle time from
    // kernel time.
    system = (kernel - idle);
    return Py_BuildValue("(fff)", user, system, idle);
}


/*
 * Same as above but for all system CPUs.
 */
static PyObject *
psutil_per_cpu_times(PyObject *self, PyObject *args) {
    // NtQuerySystemInformation stuff
    typedef DWORD (_stdcall * NTQSI_PROC) (int, PVOID, ULONG, PULONG);
    NTQSI_PROC NtQuerySystemInformation;
    HINSTANCE hNtDll;

    float idle, kernel, systemt, user, interrupt, dpc;
    NTSTATUS status;
    _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION *sppi = NULL;
    SYSTEM_INFO si;
    UINT i;
    PyObject *py_tuple = NULL;
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;

    // obtain NtQuerySystemInformation
    hNtDll = LoadLibrary(TEXT("ntdll.dll"));
    if (hNtDll == NULL) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }
    NtQuerySystemInformation = (NTQSI_PROC)GetProcAddress(
        hNtDll, "NtQuerySystemInformation");
    if (NtQuerySystemInformation == NULL) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // retrives number of processors
    GetSystemInfo(&si);

    // allocates an array of _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION
    // structures, one per processor
    sppi = (_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION *) \
           malloc(si.dwNumberOfProcessors * \
                  sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION));
    if (sppi == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    // gets cpu time informations
    status = NtQuerySystemInformation(
        SystemProcessorPerformanceInformation,
        sppi,
        si.dwNumberOfProcessors * sizeof
            (_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION),
        NULL);
    if (status != 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // computes system global times summing each
    // processor value
    idle = user = kernel = interrupt = dpc = 0;
    for (i = 0; i < si.dwNumberOfProcessors; i++) {
        py_tuple = NULL;
        user = (float)((HI_T * sppi[i].UserTime.HighPart) +
                       (LO_T * sppi[i].UserTime.LowPart));
        idle = (float)((HI_T * sppi[i].IdleTime.HighPart) +
                       (LO_T * sppi[i].IdleTime.LowPart));
        kernel = (float)((HI_T * sppi[i].KernelTime.HighPart) +
                         (LO_T * sppi[i].KernelTime.LowPart));
        interrupt = (float)((HI_T * sppi[i].InterruptTime.HighPart) +
                            (LO_T * sppi[i].InterruptTime.LowPart));
        dpc = (float)((HI_T * sppi[i].DpcTime.HighPart) +
                      (LO_T * sppi[i].DpcTime.LowPart));

        // kernel time includes idle time on windows
        // we return only busy kernel time subtracting
        // idle time from kernel time
        systemt = kernel - idle;
        py_tuple = Py_BuildValue(
            "(ddddd)",
            user,
            systemt,
            idle,
            interrupt,
            dpc
        );
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
    }

    free(sppi);
    FreeLibrary(hNtDll);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (sppi)
        free(sppi);
    if (hNtDll)
        FreeLibrary(hNtDll);
    return NULL;
}


/*
 * Return process current working directory as a Python string.
 */

static PyObject *
psutil_proc_cwd(PyObject *self, PyObject *args) {
    long pid;
    int pid_return;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    pid_return = psutil_pid_is_running(pid);
    if (pid_return == 0)
        return NoSuchProcess();
    if (pid_return == -1)
        return NULL;

    return psutil_get_cwd(pid);
}


/*
 * Resume or suspends a process
 */
int
psutil_proc_suspend_or_resume(DWORD pid, int suspend) {
    // a huge thanks to http://www.codeproject.com/KB/threads/pausep.aspx
    HANDLE hThreadSnap = NULL;
    THREADENTRY32  te32 = {0};

    if (pid == 0) {
        AccessDenied();
        return FALSE;
    }

    hThreadSnap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (hThreadSnap == INVALID_HANDLE_VALUE) {
        PyErr_SetFromWindowsErr(0);
        return FALSE;
    }

    // Fill in the size of the structure before using it
    te32.dwSize = sizeof(THREADENTRY32);

    if (! Thread32First(hThreadSnap, &te32)) {
        PyErr_SetFromWindowsErr(0);
        CloseHandle(hThreadSnap);
        return FALSE;
    }

    // Walk the thread snapshot to find all threads of the process.
    // If the thread belongs to the process, add its information
    // to the display list.
    do
    {
        if (te32.th32OwnerProcessID == pid)
        {
            HANDLE hThread = OpenThread(THREAD_SUSPEND_RESUME, FALSE,
                                        te32.th32ThreadID);
            if (hThread == NULL) {
                PyErr_SetFromWindowsErr(0);
                CloseHandle(hThread);
                CloseHandle(hThreadSnap);
                return FALSE;
            }
            if (suspend == 1)
            {
                if (SuspendThread(hThread) == (DWORD) - 1) {
                    PyErr_SetFromWindowsErr(0);
                    CloseHandle(hThread);
                    CloseHandle(hThreadSnap);
                    return FALSE;
                }
            }
            else
            {
                if (ResumeThread(hThread) == (DWORD) - 1) {
                    PyErr_SetFromWindowsErr(0);
                    CloseHandle(hThread);
                    CloseHandle(hThreadSnap);
                    return FALSE;
                }
            }
            CloseHandle(hThread);
        }
    } while (Thread32Next(hThreadSnap, &te32));

    CloseHandle(hThreadSnap);
    return TRUE;
}


static PyObject *
psutil_proc_suspend(PyObject *self, PyObject *args) {
    long pid;
    int suspend = 1;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (! psutil_proc_suspend_or_resume(pid, suspend))
        return NULL;
    Py_RETURN_NONE;
}


static PyObject *
psutil_proc_resume(PyObject *self, PyObject *args) {
    long pid;
    int suspend = 0;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (! psutil_proc_suspend_or_resume(pid, suspend))
        return NULL;
    Py_RETURN_NONE;
}


static PyObject *
psutil_proc_threads(PyObject *self, PyObject *args) {
    HANDLE hThread;
    THREADENTRY32 te32 = {0};
    long pid;
    int pid_return;
    int rc;
    FILETIME ftDummy, ftKernel, ftUser;
    HANDLE hThreadSnap = NULL;
    PyObject *py_tuple = NULL;
    PyObject *py_retlist = PyList_New(0);

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;
    if (pid == 0) {
        // raise AD instead of returning 0 as procexp is able to
        // retrieve useful information somehow
        AccessDenied();
        goto error;
    }

    pid_return = psutil_pid_is_running(pid);
    if (pid_return == 0) {
        NoSuchProcess();
        goto error;
    }
    if (pid_return == -1)
        goto error;

    hThreadSnap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (hThreadSnap == INVALID_HANDLE_VALUE) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // Fill in the size of the structure before using it
    te32.dwSize = sizeof(THREADENTRY32);

    if (! Thread32First(hThreadSnap, &te32)) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // Walk the thread snapshot to find all threads of the process.
    // If the thread belongs to the process, increase the counter.
    do {
        if (te32.th32OwnerProcessID == pid) {
            py_tuple = NULL;
            hThread = NULL;
            hThread = OpenThread(THREAD_QUERY_INFORMATION,
                                 FALSE, te32.th32ThreadID);
            if (hThread == NULL) {
                // thread has disappeared on us
                continue;
            }

            rc = GetThreadTimes(hThread, &ftDummy, &ftDummy, &ftKernel,
                                &ftUser);
            if (rc == 0) {
                PyErr_SetFromWindowsErr(0);
                goto error;
            }

            /*
             * User and kernel times are represented as a FILETIME structure
             * wich contains a 64-bit value representing the number of
             * 100-nanosecond intervals since January 1, 1601 (UTC):
             * http://msdn.microsoft.com/en-us/library/ms724284(VS.85).aspx
             * To convert it into a float representing the seconds that the
             * process has executed in user/kernel mode I borrowed the code
             * below from Python's Modules/posixmodule.c
             */
            py_tuple = Py_BuildValue(
                "kdd",
                te32.th32ThreadID,
                (double)(ftUser.dwHighDateTime * 429.4967296 + \
                         ftUser.dwLowDateTime * 1e-7),
                (double)(ftKernel.dwHighDateTime * 429.4967296 + \
                         ftKernel.dwLowDateTime * 1e-7));
            if (!py_tuple)
                goto error;
            if (PyList_Append(py_retlist, py_tuple))
                goto error;
            Py_DECREF(py_tuple);

            CloseHandle(hThread);
        }
    } while (Thread32Next(hThreadSnap, &te32));

    CloseHandle(hThreadSnap);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (hThread != NULL)
        CloseHandle(hThread);
    if (hThreadSnap != NULL)
        CloseHandle(hThreadSnap);
    return NULL;
}


static PyObject *
psutil_proc_open_files(PyObject *self, PyObject *args) {
    long       pid;
    HANDLE     processHandle;
    DWORD      access = PROCESS_DUP_HANDLE | PROCESS_QUERY_INFORMATION;
    PyObject  *py_retlist;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    processHandle = psutil_handle_from_pid_waccess(pid, access);
    if (processHandle == NULL)
        return NULL;
    py_retlist = psutil_get_open_files(pid, processHandle);
    CloseHandle(processHandle);
    if (py_retlist == NULL)
        return PyErr_SetFromWindowsErr(0);
    return py_retlist;
}


/*
 Accept a filename's drive in native  format like "\Device\HarddiskVolume1\"
 and return the corresponding drive letter (e.g. "C:\\").
 If no match is found return an empty string.
*/
static PyObject *
psutil_win32_QueryDosDevice(PyObject *self, PyObject *args) {
    LPCTSTR   lpDevicePath;
    TCHAR d = TEXT('A');
    TCHAR     szBuff[5];

    if (!PyArg_ParseTuple(args, "s", &lpDevicePath))
        return NULL;

    while (d <= TEXT('Z')) {
        TCHAR szDeviceName[3] = {d, TEXT(':'), TEXT('\0')};
        TCHAR szTarget[512] = {0};
        if (QueryDosDevice(szDeviceName, szTarget, 511) != 0) {
            if (_tcscmp(lpDevicePath, szTarget) == 0) {
                _stprintf_s(szBuff, _countof(szBuff), TEXT("%c:"), d);
                return Py_BuildValue("s", szBuff);
            }
        }
        d++;
    }
    return Py_BuildValue("s", "");
}


/*
 * Return process username as a "DOMAIN//USERNAME" string.
 */
static PyObject *
psutil_proc_username(PyObject *self, PyObject *args) {
    long pid;
    HANDLE processHandle;
    HANDLE tokenHandle;
    PTOKEN_USER user;
    ULONG bufferSize;
    PTSTR name;
    ULONG nameSize;
    PTSTR domainName;
    ULONG domainNameSize;
    SID_NAME_USE nameUse;
    PTSTR fullName;
    PyObject *py_unicode;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;

    processHandle = psutil_handle_from_pid_waccess(
        pid, PROCESS_QUERY_INFORMATION);
    if (processHandle == NULL)
        return NULL;

    if (!OpenProcessToken(processHandle, TOKEN_QUERY, &tokenHandle)) {
        CloseHandle(processHandle);
        return PyErr_SetFromWindowsErr(0);
    }

    CloseHandle(processHandle);

    // Get the user SID.

    bufferSize = 0x100;
    user = malloc(bufferSize);
    if (user == NULL)
        return PyErr_NoMemory();

    if (!GetTokenInformation(tokenHandle, TokenUser, user, bufferSize,
                             &bufferSize))
    {
        free(user);
        user = malloc(bufferSize);
        if (user == NULL) {
            CloseHandle(tokenHandle);
            return PyErr_NoMemory();
        }
        if (!GetTokenInformation(tokenHandle, TokenUser, user, bufferSize,
                                 &bufferSize))
        {
            free(user);
            CloseHandle(tokenHandle);
            return PyErr_SetFromWindowsErr(0);
        }
    }

    CloseHandle(tokenHandle);

    // resolve the SID to a name
    nameSize = 0x100;
    domainNameSize = 0x100;

    name = malloc(nameSize * sizeof(TCHAR));
    if (name == NULL)
        return PyErr_NoMemory();
    domainName = malloc(domainNameSize * sizeof(TCHAR));
    if (domainName == NULL)
        return PyErr_NoMemory();

    if (!LookupAccountSid(NULL, user->User.Sid, name, &nameSize, domainName,
                          &domainNameSize, &nameUse))
    {
        free(name);
        free(domainName);
        name = malloc(nameSize * sizeof(TCHAR));
        if (name == NULL)
            return PyErr_NoMemory();
        domainName = malloc(domainNameSize * sizeof(TCHAR));
        if (domainName == NULL)
            return PyErr_NoMemory();
        if (!LookupAccountSid(NULL, user->User.Sid, name, &nameSize,
                              domainName, &domainNameSize, &nameUse))
        {
            free(name);
            free(domainName);
            free(user);

            return PyErr_SetFromWindowsErr(0);
        }
    }

    nameSize = _tcslen(name);
    domainNameSize = _tcslen(domainName);

    // build the full username string
    fullName = malloc((domainNameSize + 1 + nameSize + 1) * sizeof(TCHAR));
    if (fullName == NULL) {
        free(name);
        free(domainName);
        free(user);
        return PyErr_NoMemory();
    }
    memcpy(fullName, domainName, domainNameSize);
    fullName[domainNameSize] = '\\';
    memcpy(&fullName[domainNameSize + 1], name, nameSize);
    fullName[domainNameSize + 1 + nameSize] = '\0';

#if PY_MAJOR_VERSION >= 3 && PY_MINOR_VERSION >= 3
    py_unicode = PyUnicode_DecodeLocaleAndSize(
        fullName, _tcslen(fullName), "surrogateescape");
#else
    py_unicode = PyUnicode_Decode(
        fullName, _tcslen(fullName), Py_FileSystemDefaultEncoding, "replace");
#endif

    free(fullName);
    free(name);
    free(domainName);
    free(user);

    return py_unicode;
}


typedef DWORD (WINAPI * _GetExtendedTcpTable)(PVOID, PDWORD, BOOL, ULONG,
                                              TCP_TABLE_CLASS, ULONG);


// https://msdn.microsoft.com/library/aa365928.aspx
static DWORD __GetExtendedTcpTable(_GetExtendedTcpTable call,
                                   ULONG address_family,
                                   PVOID * data, DWORD * size)
{
    // Due to other processes being active on the machine, it's possible
    // that the size of the table increases between the moment where we
    // query the size and the moment where we query the data.  Therefore, it's
    // important to call this in a loop to retry if that happens.
    //
    // Also, since we may loop a theoretically unbounded number of times here,
    // release the GIL while we're doing this.
    DWORD error = ERROR_INSUFFICIENT_BUFFER;
    *size = 0;
    *data = NULL;
    Py_BEGIN_ALLOW_THREADS;
    error = call(NULL, size, FALSE, address_family,
                 TCP_TABLE_OWNER_PID_ALL, 0);
    while (error == ERROR_INSUFFICIENT_BUFFER)
    {
        *data = malloc(*size);
        if (*data == NULL) {
            error = ERROR_NOT_ENOUGH_MEMORY;
            continue;
        }
        error = call(*data, size, FALSE, address_family,
                     TCP_TABLE_OWNER_PID_ALL, 0);
        if (error != NO_ERROR) {
            free(*data);
            *data = NULL;
        }
    }
    Py_END_ALLOW_THREADS;
    return error;
}


typedef DWORD (WINAPI * _GetExtendedUdpTable)(PVOID, PDWORD, BOOL, ULONG,
                                              UDP_TABLE_CLASS, ULONG);


// https://msdn.microsoft.com/library/aa365930.aspx
static DWORD __GetExtendedUdpTable(_GetExtendedUdpTable call,
                                   ULONG address_family,
                                   PVOID * data, DWORD * size)
{
    // Due to other processes being active on the machine, it's possible
    // that the size of the table increases between the moment where we
    // query the size and the moment where we query the data.  Therefore, it's
    // important to call this in a loop to retry if that happens.
    //
    // Also, since we may loop a theoretically unbounded number of times here,
    // release the GIL while we're doing this.
    DWORD error = ERROR_INSUFFICIENT_BUFFER;
    *size = 0;
    *data = NULL;
    Py_BEGIN_ALLOW_THREADS;
    error = call(NULL, size, FALSE, address_family,
                 UDP_TABLE_OWNER_PID, 0);
    while (error == ERROR_INSUFFICIENT_BUFFER)
    {
        *data = malloc(*size);
        if (*data == NULL) {
            error = ERROR_NOT_ENOUGH_MEMORY;
            continue;
        }
        error = call(*data, size, FALSE, address_family,
                     UDP_TABLE_OWNER_PID, 0);
        if (error != NO_ERROR) {
            free(*data);
            *data = NULL;
        }
    }
    Py_END_ALLOW_THREADS;
    return error;
}


/*
 * Return a list of network connections opened by a process
 */
static PyObject *
psutil_net_connections(PyObject *self, PyObject *args) {
    static long null_address[4] = { 0, 0, 0, 0 };
    unsigned long pid;
    typedef PSTR (NTAPI * _RtlIpv4AddressToStringA)(struct in_addr *, PSTR);
    _RtlIpv4AddressToStringA rtlIpv4AddressToStringA;
    typedef PSTR (NTAPI * _RtlIpv6AddressToStringA)(struct in6_addr *, PSTR);
    _RtlIpv6AddressToStringA rtlIpv6AddressToStringA;
    _GetExtendedTcpTable getExtendedTcpTable;
    _GetExtendedUdpTable getExtendedUdpTable;
    PVOID table = NULL;
    DWORD tableSize;
    DWORD error;
    PMIB_TCPTABLE_OWNER_PID tcp4Table;
    PMIB_UDPTABLE_OWNER_PID udp4Table;
    PMIB_TCP6TABLE_OWNER_PID tcp6Table;
    PMIB_UDP6TABLE_OWNER_PID udp6Table;
    ULONG i;
    CHAR addressBufferLocal[65];
    CHAR addressBufferRemote[65];

    PyObject *py_retlist;
    PyObject *py_conn_tuple = NULL;
    PyObject *py_af_filter = NULL;
    PyObject *py_type_filter = NULL;
    PyObject *py_addr_tuple_local = NULL;
    PyObject *py_addr_tuple_remote = NULL;
    PyObject *_AF_INET = PyLong_FromLong((long)AF_INET);
    PyObject *_AF_INET6 = PyLong_FromLong((long)AF_INET6);
    PyObject *_SOCK_STREAM = PyLong_FromLong((long)SOCK_STREAM);
    PyObject *_SOCK_DGRAM = PyLong_FromLong((long)SOCK_DGRAM);

    if (! PyArg_ParseTuple(args, "lOO", &pid, &py_af_filter, &py_type_filter))
    {
        _psutil_conn_decref_objs();
        return NULL;
    }

    if (!PySequence_Check(py_af_filter) || !PySequence_Check(py_type_filter)) {
        _psutil_conn_decref_objs();
        PyErr_SetString(PyExc_TypeError, "arg 2 or 3 is not a sequence");
        return NULL;
    }

    if (pid != -1) {
        if (psutil_pid_is_running(pid) == 0) {
            _psutil_conn_decref_objs();
            return NoSuchProcess();
        }
    }

    // Import some functions.
    {
        HMODULE ntdll;
        HMODULE iphlpapi;

        ntdll = LoadLibrary(TEXT("ntdll.dll"));
        rtlIpv4AddressToStringA = (_RtlIpv4AddressToStringA)GetProcAddress(
                                   ntdll, "RtlIpv4AddressToStringA");
        rtlIpv6AddressToStringA = (_RtlIpv6AddressToStringA)GetProcAddress(
                                   ntdll, "RtlIpv6AddressToStringA");
        /* TODO: Check these two function pointers */

        iphlpapi = LoadLibrary(TEXT("iphlpapi.dll"));
        getExtendedTcpTable = (_GetExtendedTcpTable)GetProcAddress(iphlpapi,
                              "GetExtendedTcpTable");
        getExtendedUdpTable = (_GetExtendedUdpTable)GetProcAddress(iphlpapi,
                              "GetExtendedUdpTable");
        FreeLibrary(ntdll);
        FreeLibrary(iphlpapi);
    }

    if ((getExtendedTcpTable == NULL) || (getExtendedUdpTable == NULL)) {
        PyErr_SetString(PyExc_NotImplementedError,
                        "feature not supported on this Windows version");
        _psutil_conn_decref_objs();
        return NULL;
    }

    py_retlist = PyList_New(0);
    if (py_retlist == NULL) {
        _psutil_conn_decref_objs();
        return NULL;
    }

    // TCP IPv4

    if ((PySequence_Contains(py_af_filter, _AF_INET) == 1) &&
            (PySequence_Contains(py_type_filter, _SOCK_STREAM) == 1))
    {
        table = NULL;
        py_conn_tuple = NULL;
        py_addr_tuple_local = NULL;
        py_addr_tuple_remote = NULL;
        tableSize = 0;

        error = __GetExtendedTcpTable(getExtendedTcpTable,
                                      AF_INET, &table, &tableSize);
        if (error == ERROR_NOT_ENOUGH_MEMORY) {
            PyErr_NoMemory();
            goto error;
        }

        if (error == NO_ERROR)
        {
            tcp4Table = table;

            for (i = 0; i < tcp4Table->dwNumEntries; i++)
            {
                if (pid != -1) {
                    if (tcp4Table->table[i].dwOwningPid != pid) {
                        continue;
                    }
                }

                if (tcp4Table->table[i].dwLocalAddr != 0 ||
                        tcp4Table->table[i].dwLocalPort != 0)
                {
                    struct in_addr addr;

                    addr.S_un.S_addr = tcp4Table->table[i].dwLocalAddr;
                    rtlIpv4AddressToStringA(&addr, addressBufferLocal);
                    py_addr_tuple_local = Py_BuildValue(
                        "(si)",
                        addressBufferLocal,
                        BYTESWAP_USHORT(tcp4Table->table[i].dwLocalPort));
                }
                else {
                    py_addr_tuple_local = PyTuple_New(0);
                }

                if (py_addr_tuple_local == NULL)
                    goto error;

                // On Windows <= XP, remote addr is filled even if socket
                // is in LISTEN mode in which case we just ignore it.
                if ((tcp4Table->table[i].dwRemoteAddr != 0 ||
                        tcp4Table->table[i].dwRemotePort != 0) &&
                        (tcp4Table->table[i].dwState != MIB_TCP_STATE_LISTEN))
                {
                    struct in_addr addr;

                    addr.S_un.S_addr = tcp4Table->table[i].dwRemoteAddr;
                    rtlIpv4AddressToStringA(&addr, addressBufferRemote);
                    py_addr_tuple_remote = Py_BuildValue(
                        "(si)",
                        addressBufferRemote,
                        BYTESWAP_USHORT(tcp4Table->table[i].dwRemotePort));
                }
                else
                {
                    py_addr_tuple_remote = PyTuple_New(0);
                }

                if (py_addr_tuple_remote == NULL)
                    goto error;

                py_conn_tuple = Py_BuildValue(
                    "(iiiNNiI)",
                    -1,
                    AF_INET,
                    SOCK_STREAM,
                    py_addr_tuple_local,
                    py_addr_tuple_remote,
                    tcp4Table->table[i].dwState,
                    tcp4Table->table[i].dwOwningPid);
                if (!py_conn_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_conn_tuple))
                    goto error;
                Py_DECREF(py_conn_tuple);
            }
        }
        else {
            PyErr_SetFromWindowsErr(error);
            goto error;
        }

        free(table);
        table = NULL;
        tableSize = 0;
    }

    // TCP IPv6
    if ((PySequence_Contains(py_af_filter, _AF_INET6) == 1) &&
            (PySequence_Contains(py_type_filter, _SOCK_STREAM) == 1))
    {
        table = NULL;
        py_conn_tuple = NULL;
        py_addr_tuple_local = NULL;
        py_addr_tuple_remote = NULL;
        tableSize = 0;

        error = __GetExtendedTcpTable(getExtendedTcpTable,
                                      AF_INET6, &table, &tableSize);
        if (error == ERROR_NOT_ENOUGH_MEMORY) {
            PyErr_NoMemory();
            goto error;
        }

        if (error == NO_ERROR)
        {
            tcp6Table = table;

            for (i = 0; i < tcp6Table->dwNumEntries; i++)
            {
                if (pid != -1) {
                    if (tcp6Table->table[i].dwOwningPid != pid) {
                        continue;
                    }
                }

                if (memcmp(tcp6Table->table[i].ucLocalAddr, null_address, 16)
                        != 0 || tcp6Table->table[i].dwLocalPort != 0)
                {
                    struct in6_addr addr;

                    memcpy(&addr, tcp6Table->table[i].ucLocalAddr, 16);
                    rtlIpv6AddressToStringA(&addr, addressBufferLocal);
                    py_addr_tuple_local = Py_BuildValue(
                        "(si)",
                        addressBufferLocal,
                        BYTESWAP_USHORT(tcp6Table->table[i].dwLocalPort));
                }
                else {
                    py_addr_tuple_local = PyTuple_New(0);
                }

                if (py_addr_tuple_local == NULL)
                    goto error;

                // On Windows <= XP, remote addr is filled even if socket
                // is in LISTEN mode in which case we just ignore it.
                if ((memcmp(tcp6Table->table[i].ucRemoteAddr, null_address, 16)
                        != 0 ||
                        tcp6Table->table[i].dwRemotePort != 0) &&
                        (tcp6Table->table[i].dwState != MIB_TCP_STATE_LISTEN))
                {
                    struct in6_addr addr;

                    memcpy(&addr, tcp6Table->table[i].ucRemoteAddr, 16);
                    rtlIpv6AddressToStringA(&addr, addressBufferRemote);
                    py_addr_tuple_remote = Py_BuildValue(
                        "(si)",
                        addressBufferRemote,
                        BYTESWAP_USHORT(tcp6Table->table[i].dwRemotePort));
                }
                else {
                    py_addr_tuple_remote = PyTuple_New(0);
                }

                if (py_addr_tuple_remote == NULL)
                    goto error;

                py_conn_tuple = Py_BuildValue(
                    "(iiiNNiI)",
                    -1,
                    AF_INET6,
                    SOCK_STREAM,
                    py_addr_tuple_local,
                    py_addr_tuple_remote,
                    tcp6Table->table[i].dwState,
                    tcp6Table->table[i].dwOwningPid);
                if (!py_conn_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_conn_tuple))
                    goto error;
                Py_DECREF(py_conn_tuple);
            }
        }
        else {
            PyErr_SetFromWindowsErr(error);
            goto error;
        }

        free(table);
        table = NULL;
        tableSize = 0;
    }

    // UDP IPv4

    if ((PySequence_Contains(py_af_filter, _AF_INET) == 1) &&
            (PySequence_Contains(py_type_filter, _SOCK_DGRAM) == 1))
    {
        table = NULL;
        py_conn_tuple = NULL;
        py_addr_tuple_local = NULL;
        py_addr_tuple_remote = NULL;
        tableSize = 0;
        error = __GetExtendedUdpTable(getExtendedUdpTable,
                                      AF_INET, &table, &tableSize);
        if (error == ERROR_NOT_ENOUGH_MEMORY) {
            PyErr_NoMemory();
            goto error;
        }

        if (error == NO_ERROR)
        {
            udp4Table = table;

            for (i = 0; i < udp4Table->dwNumEntries; i++)
            {
                if (pid != -1) {
                    if (udp4Table->table[i].dwOwningPid != pid) {
                        continue;
                    }
                }

                if (udp4Table->table[i].dwLocalAddr != 0 ||
                    udp4Table->table[i].dwLocalPort != 0)
                {
                    struct in_addr addr;

                    addr.S_un.S_addr = udp4Table->table[i].dwLocalAddr;
                    rtlIpv4AddressToStringA(&addr, addressBufferLocal);
                    py_addr_tuple_local = Py_BuildValue(
                        "(si)",
                        addressBufferLocal,
                        BYTESWAP_USHORT(udp4Table->table[i].dwLocalPort));
                }
                else {
                    py_addr_tuple_local = PyTuple_New(0);
                }

                if (py_addr_tuple_local == NULL)
                    goto error;

                py_conn_tuple = Py_BuildValue(
                    "(iiiNNiI)",
                    -1,
                    AF_INET,
                    SOCK_DGRAM,
                    py_addr_tuple_local,
                    PyTuple_New(0),
                    PSUTIL_CONN_NONE,
                    udp4Table->table[i].dwOwningPid);
                if (!py_conn_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_conn_tuple))
                    goto error;
                Py_DECREF(py_conn_tuple);
            }
        }
        else {
            PyErr_SetFromWindowsErr(error);
            goto error;
        }

        free(table);
        table = NULL;
        tableSize = 0;
    }

    // UDP IPv6

    if ((PySequence_Contains(py_af_filter, _AF_INET6) == 1) &&
            (PySequence_Contains(py_type_filter, _SOCK_DGRAM) == 1))
    {
        table = NULL;
        py_conn_tuple = NULL;
        py_addr_tuple_local = NULL;
        py_addr_tuple_remote = NULL;
        tableSize = 0;
        error = __GetExtendedUdpTable(getExtendedUdpTable,
                                      AF_INET6, &table, &tableSize);
        if (error == ERROR_NOT_ENOUGH_MEMORY) {
            PyErr_NoMemory();
            goto error;
        }

        if (error == NO_ERROR)
        {
            udp6Table = table;

            for (i = 0; i < udp6Table->dwNumEntries; i++) {
                if (pid != -1) {
                    if (udp6Table->table[i].dwOwningPid != pid) {
                        continue;
                    }
                }

                if (memcmp(udp6Table->table[i].ucLocalAddr, null_address, 16)
                        != 0 || udp6Table->table[i].dwLocalPort != 0)
                {
                    struct in6_addr addr;

                    memcpy(&addr, udp6Table->table[i].ucLocalAddr, 16);
                    rtlIpv6AddressToStringA(&addr, addressBufferLocal);
                    py_addr_tuple_local = Py_BuildValue(
                        "(si)",
                        addressBufferLocal,
                        BYTESWAP_USHORT(udp6Table->table[i].dwLocalPort));
                }
                else {
                    py_addr_tuple_local = PyTuple_New(0);
                }

                if (py_addr_tuple_local == NULL)
                    goto error;

                py_conn_tuple = Py_BuildValue(
                    "(iiiNNiI)",
                    -1,
                    AF_INET6,
                    SOCK_DGRAM,
                    py_addr_tuple_local,
                    PyTuple_New(0),
                    PSUTIL_CONN_NONE,
                    udp6Table->table[i].dwOwningPid);
                if (!py_conn_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_conn_tuple))
                    goto error;
                Py_DECREF(py_conn_tuple);
            }
        }
        else {
            PyErr_SetFromWindowsErr(error);
            goto error;
        }

        free(table);
        table = NULL;
        tableSize = 0;
    }

    _psutil_conn_decref_objs();
    return py_retlist;

error:
    _psutil_conn_decref_objs();
    Py_XDECREF(py_conn_tuple);
    Py_XDECREF(py_addr_tuple_local);
    Py_XDECREF(py_addr_tuple_remote);
    Py_DECREF(py_retlist);
    if (table != NULL)
        free(table);
    return NULL;
}


/*
 * Get process priority as a Python integer.
 */
static PyObject *
psutil_proc_priority_get(PyObject *self, PyObject *args) {
    long pid;
    DWORD priority;
    HANDLE hProcess;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL)
        return NULL;
    priority = GetPriorityClass(hProcess);
    CloseHandle(hProcess);
    if (priority == 0) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    return Py_BuildValue("i", priority);
}


/*
 * Set process priority.
 */
static PyObject *
psutil_proc_priority_set(PyObject *self, PyObject *args) {
    long pid;
    int priority;
    int retval;
    HANDLE hProcess;
    DWORD access = PROCESS_QUERY_INFORMATION | PROCESS_SET_INFORMATION;

    if (! PyArg_ParseTuple(args, "li", &pid, &priority))
        return NULL;
    hProcess = psutil_handle_from_pid_waccess(pid, access);
    if (hProcess == NULL)
        return NULL;
    retval = SetPriorityClass(hProcess, priority);
    CloseHandle(hProcess);
    if (retval == 0) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    Py_RETURN_NONE;
}


#if (_WIN32_WINNT >= 0x0600)  // Windows Vista
/*
 * Get process IO priority as a Python integer.
 */
static PyObject *
psutil_proc_io_priority_get(PyObject *self, PyObject *args) {
    long pid;
    HANDLE hProcess;
    PULONG IoPriority;

    _NtQueryInformationProcess NtQueryInformationProcess =
        (_NtQueryInformationProcess)GetProcAddress(
            GetModuleHandleA("ntdll.dll"), "NtQueryInformationProcess");

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL)
        return NULL;

    NtQueryInformationProcess(
        hProcess,
        ProcessIoPriority,
        &IoPriority,
        sizeof(ULONG),
        NULL
    );
    CloseHandle(hProcess);
    return Py_BuildValue("i", IoPriority);
}


/*
 * Set process IO priority.
 */
static PyObject *
psutil_proc_io_priority_set(PyObject *self, PyObject *args) {
    long pid;
    int prio;
    HANDLE hProcess;

    _NtSetInformationProcess NtSetInformationProcess =
        (_NtSetInformationProcess)GetProcAddress(
            GetModuleHandleA("ntdll.dll"), "NtSetInformationProcess");

    if (NtSetInformationProcess == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "couldn't get NtSetInformationProcess syscall");
        return NULL;
    }

    if (! PyArg_ParseTuple(args, "li", &pid, &prio))
        return NULL;
    hProcess = psutil_handle_from_pid_waccess(pid, PROCESS_ALL_ACCESS);
    if (hProcess == NULL)
        return NULL;

    NtSetInformationProcess(
        hProcess,
        ProcessIoPriority,
        (PVOID)&prio,
        sizeof((PVOID)prio)
    );

    CloseHandle(hProcess);
    Py_RETURN_NONE;
}
#endif


/*
 * Return a Python tuple referencing process I/O counters.
 */
static PyObject *
psutil_proc_io_counters(PyObject *self, PyObject *args) {
    DWORD pid;
    HANDLE hProcess;
    IO_COUNTERS IoCounters;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid(pid);
    if (NULL == hProcess)
        return NULL;
    if (! GetProcessIoCounters(hProcess, &IoCounters)) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(0);
    }
    CloseHandle(hProcess);
    return Py_BuildValue("(KKKKKK)",
                         IoCounters.ReadOperationCount,
                         IoCounters.WriteOperationCount,
                         IoCounters.ReadTransferCount,
                         IoCounters.WriteTransferCount,
                         IoCounters.OtherOperationCount,
                         IoCounters.OtherTransferCount);
}


/*
 * Return process CPU affinity as a bitmask
 */
static PyObject *
psutil_proc_cpu_affinity_get(PyObject *self, PyObject *args) {
    DWORD pid;
    HANDLE hProcess;
    DWORD_PTR proc_mask;
    DWORD_PTR system_mask;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL) {
        return NULL;
    }
    if (GetProcessAffinityMask(hProcess, &proc_mask, &system_mask) == 0) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(0);
    }

    CloseHandle(hProcess);
#ifdef _WIN64
    return Py_BuildValue("K", (unsigned long long)proc_mask);
#else
    return Py_BuildValue("k", (unsigned long)proc_mask);
#endif
}


/*
 * Set process CPU affinity
 */
static PyObject *
psutil_proc_cpu_affinity_set(PyObject *self, PyObject *args) {
    DWORD pid;
    HANDLE hProcess;
    DWORD dwDesiredAccess = \
        PROCESS_QUERY_INFORMATION | PROCESS_SET_INFORMATION;
    DWORD_PTR mask;

#ifdef _WIN64
    if (! PyArg_ParseTuple(args, "lK", &pid, &mask))
#else
    if (! PyArg_ParseTuple(args, "lk", &pid, &mask))
#endif
    {
        return NULL;
    }
    hProcess = psutil_handle_from_pid_waccess(pid, dwDesiredAccess);
    if (hProcess == NULL)
        return NULL;

    if (SetProcessAffinityMask(hProcess, mask) == 0) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(0);
    }

    CloseHandle(hProcess);
    Py_RETURN_NONE;
}


/*
 * Return True if one of the process threads is in a waiting or
 * suspended status.
 */
static PyObject *
psutil_proc_is_suspended(PyObject *self, PyObject *args) {
    DWORD pid;
    ULONG i;
    PSYSTEM_PROCESS_INFORMATION process;
    PVOID buffer;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (! psutil_get_proc_info(pid, &process, &buffer)) {
        return NULL;
    }
    for (i = 0; i < process->NumberOfThreads; i++) {
        if (process->Threads[i].ThreadState != Waiting ||
                process->Threads[i].WaitReason != Suspended)
        {
            free(buffer);
            Py_RETURN_FALSE;
        }
    }
    free(buffer);
    Py_RETURN_TRUE;
}


/*
 * Return path's disk total and free as a Python tuple.
 */
static PyObject *
psutil_disk_usage(PyObject *self, PyObject *args) {
    BOOL retval;
    ULARGE_INTEGER _, total, free;
    char *path;

    if (PyArg_ParseTuple(args, "u", &path)) {
        Py_BEGIN_ALLOW_THREADS
        retval = GetDiskFreeSpaceExW((LPCWSTR)path, &_, &total, &free);
        Py_END_ALLOW_THREADS
        goto return_;
    }

    // on Python 2 we also want to accept plain strings other
    // than Unicode
#if PY_MAJOR_VERSION <= 2
    PyErr_Clear();  // drop the argument parsing error
    if (PyArg_ParseTuple(args, "s", &path)) {
        Py_BEGIN_ALLOW_THREADS
        retval = GetDiskFreeSpaceEx(path, &_, &total, &free);
        Py_END_ALLOW_THREADS
        goto return_;
    }
#endif

    return NULL;

return_:
    if (retval == 0)
        return PyErr_SetFromWindowsErr(0);
    else
        return Py_BuildValue("(LL)", total.QuadPart, free.QuadPart);
}


/*
 * Return a Python list of named tuples with overall network I/O information
 */
static PyObject *
psutil_net_io_counters(PyObject *self, PyObject *args) {
    DWORD dwRetVal = 0;

#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
    MIB_IF_ROW2 *pIfRow = NULL;
#else // Windows XP
    MIB_IFROW *pIfRow = NULL;
#endif

    PIP_ADAPTER_ADDRESSES pAddresses = NULL;
    PIP_ADAPTER_ADDRESSES pCurrAddresses = NULL;
    PyObject *py_retdict = PyDict_New();
    PyObject *py_nic_info = NULL;
    PyObject *py_nic_name = NULL;

    if (py_retdict == NULL)
        return NULL;
    pAddresses = psutil_get_nic_addresses();
    if (pAddresses == NULL)
        goto error;
    pCurrAddresses = pAddresses;

    while (pCurrAddresses) {
        py_nic_name = NULL;
        py_nic_info = NULL;

#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
        pIfRow = (MIB_IF_ROW2 *) malloc(sizeof(MIB_IF_ROW2));
#else // Windows XP
        pIfRow = (MIB_IFROW *) malloc(sizeof(MIB_IFROW));
#endif

        if (pIfRow == NULL) {
            PyErr_NoMemory();
            goto error;
        }

#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
        SecureZeroMemory((PVOID)pIfRow, sizeof(MIB_IF_ROW2));
        pIfRow->InterfaceIndex = pCurrAddresses->IfIndex;
        dwRetVal = GetIfEntry2(pIfRow);
#else // Windows XP
        pIfRow->dwIndex = pCurrAddresses->IfIndex;
        dwRetVal = GetIfEntry(pIfRow);
#endif

        if (dwRetVal != NO_ERROR) {
            PyErr_SetString(PyExc_RuntimeError,
                            "GetIfEntry() or GetIfEntry2() syscalls failed.");
            goto error;
        }

#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
        py_nic_info = Py_BuildValue("(KKKKKKKK)",
                                    pIfRow->OutOctets,
                                    pIfRow->InOctets,
                                    pIfRow->OutUcastPkts,
                                    pIfRow->InUcastPkts,
                                    pIfRow->InErrors,
                                    pIfRow->OutErrors,
                                    pIfRow->InDiscards,
                                    pIfRow->OutDiscards);
#else // Windows XP
        py_nic_info = Py_BuildValue("(kkkkkkkk)",
                                    pIfRow->dwOutOctets,
                                    pIfRow->dwInOctets,
                                    pIfRow->dwOutUcastPkts,
                                    pIfRow->dwInUcastPkts,
                                    pIfRow->dwInErrors,
                                    pIfRow->dwOutErrors,
                                    pIfRow->dwInDiscards,
                                    pIfRow->dwOutDiscards);
#endif

        if (!py_nic_info)
            goto error;

        py_nic_name = PyUnicode_FromWideChar(
            pCurrAddresses->FriendlyName,
            wcslen(pCurrAddresses->FriendlyName));

        if (py_nic_name == NULL)
            goto error;
        if (PyDict_SetItem(py_retdict, py_nic_name, py_nic_info))
            goto error;
        Py_XDECREF(py_nic_name);
        Py_XDECREF(py_nic_info);

        free(pIfRow);
        pCurrAddresses = pCurrAddresses->Next;
    }

    free(pAddresses);
    return py_retdict;

error:
    Py_XDECREF(py_nic_name);
    Py_XDECREF(py_nic_info);
    Py_DECREF(py_retdict);
    if (pAddresses != NULL)
        free(pAddresses);
    if (pIfRow != NULL)
        free(pIfRow);
    return NULL;
}


/*
 * Return a Python dict of tuples for disk I/O information
 */
static PyObject *
psutil_disk_io_counters(PyObject *self, PyObject *args) {
    DISK_PERFORMANCE_WIN_2008 diskPerformance;
    DWORD dwSize;
    HANDLE hDevice = NULL;
    char szDevice[MAX_PATH];
    char szDeviceDisplay[MAX_PATH];
    int devNum;
    PyObject *py_retdict = PyDict_New();
    PyObject *py_tuple = NULL;

    if (py_retdict == NULL)
        return NULL;
    // Apparently there's no way to figure out how many times we have
    // to iterate in order to find valid drives.
    // Let's assume 32, which is higher than 26, the number of letters
    // in the alphabet (from A:\ to Z:\).
    for (devNum = 0; devNum <= 32; ++devNum) {
        py_tuple = NULL;
        sprintf_s(szDevice, MAX_PATH, "\\\\.\\PhysicalDrive%d", devNum);
        hDevice = CreateFile(szDevice, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             NULL, OPEN_EXISTING, 0, NULL);

        if (hDevice == INVALID_HANDLE_VALUE)
            continue;
        if (DeviceIoControl(hDevice, IOCTL_DISK_PERFORMANCE, NULL, 0,
                            &diskPerformance, sizeof(diskPerformance),
                            &dwSize, NULL))
        {
            sprintf_s(szDeviceDisplay, MAX_PATH, "PhysicalDrive%d", devNum);
            py_tuple = Py_BuildValue(
                "(IILLKK)",
                diskPerformance.ReadCount,
                diskPerformance.WriteCount,
                diskPerformance.BytesRead,
                diskPerformance.BytesWritten,
                (unsigned long long)(diskPerformance.ReadTime.QuadPart * 10) / 1000,
                (unsigned long long)(diskPerformance.WriteTime.QuadPart * 10) / 1000);
            if (!py_tuple)
                goto error;
            if (PyDict_SetItemString(py_retdict, szDeviceDisplay,
                                     py_tuple))
            {
                goto error;
            }
            Py_XDECREF(py_tuple);
        }
        else {
            // XXX we might get here with ERROR_INSUFFICIENT_BUFFER when
            // compiling with mingw32; not sure what to do.
            // return PyErr_SetFromWindowsErr(0);
            ;;
        }

        CloseHandle(hDevice);
    }

    return py_retdict;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retdict);
    if (hDevice != NULL)
        CloseHandle(hDevice);
    return NULL;
}


static char *psutil_get_drive_type(int type) {
    switch (type) {
        case DRIVE_FIXED:
            return "fixed";
        case DRIVE_CDROM:
            return "cdrom";
        case DRIVE_REMOVABLE:
            return "removable";
        case DRIVE_UNKNOWN:
            return "unknown";
        case DRIVE_NO_ROOT_DIR:
            return "unmounted";
        case DRIVE_REMOTE:
            return "remote";
        case DRIVE_RAMDISK:
            return "ramdisk";
        default:
            return "?";
    }
}


#ifndef _ARRAYSIZE
#define _ARRAYSIZE(a) (sizeof(a)/sizeof(a[0]))
#endif

/*
 * Return disk partitions as a list of tuples such as
 * (drive_letter, drive_letter, type, "")
 */
static PyObject *
psutil_disk_partitions(PyObject *self, PyObject *args) {
    DWORD num_bytes;
    char drive_strings[255];
    char *drive_letter = drive_strings;
    int all;
    int type;
    int ret;
    char opts[20];
    LPTSTR fs_type[MAX_PATH + 1] = { 0 };
    DWORD pflags = 0;
    PyObject *py_all;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL) {
        return NULL;
    }

    // avoid to visualize a message box in case something goes wrong
    // see https://github.com/giampaolo/psutil/issues/264
    SetErrorMode(SEM_FAILCRITICALERRORS);

    if (! PyArg_ParseTuple(args, "O", &py_all))
        goto error;
    all = PyObject_IsTrue(py_all);

    Py_BEGIN_ALLOW_THREADS
    num_bytes = GetLogicalDriveStrings(254, drive_letter);
    Py_END_ALLOW_THREADS

    if (num_bytes == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    while (*drive_letter != 0) {
        py_tuple = NULL;
        opts[0] = 0;
        fs_type[0] = 0;

        Py_BEGIN_ALLOW_THREADS
        type = GetDriveType(drive_letter);
        Py_END_ALLOW_THREADS

        // by default we only show hard drives and cd-roms
        if (all == 0) {
            if ((type == DRIVE_UNKNOWN) ||
                    (type == DRIVE_NO_ROOT_DIR) ||
                    (type == DRIVE_REMOTE) ||
                    (type == DRIVE_RAMDISK)) {
                goto next;
            }
            // floppy disk: skip it by default as it introduces a
            // considerable slowdown.
            if ((type == DRIVE_REMOVABLE) &&
                    (strcmp(drive_letter, "A:\\")  == 0)) {
                goto next;
            }
        }

        ret = GetVolumeInformation(
            (LPCTSTR)drive_letter, NULL, _ARRAYSIZE(drive_letter),
            NULL, NULL, &pflags, (LPTSTR)fs_type, _ARRAYSIZE(fs_type));
        if (ret == 0) {
            // We might get here in case of a floppy hard drive, in
            // which case the error is (21, "device not ready").
            // Let's pretend it didn't happen as we already have
            // the drive name and type ('removable').
            strcat_s(opts, _countof(opts), "");
            SetLastError(0);
        }
        else {
            if (pflags & FILE_READ_ONLY_VOLUME)
                strcat_s(opts, _countof(opts), "ro");
            else
                strcat_s(opts, _countof(opts), "rw");
            if (pflags & FILE_VOLUME_IS_COMPRESSED)
                strcat_s(opts, _countof(opts), ",compressed");
        }

        if (strlen(opts) > 0)
            strcat_s(opts, _countof(opts), ",");
        strcat_s(opts, _countof(opts), psutil_get_drive_type(type));

        py_tuple = Py_BuildValue(
            "(ssss)",
            drive_letter,
            drive_letter,
            fs_type,  // either FAT, FAT32, NTFS, HPFS, CDFS, UDF or NWFS
            opts);
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_tuple);
        goto next;

next:
        drive_letter = strchr(drive_letter, 0) + 1;
    }

    SetErrorMode(0);
    return py_retlist;

error:
    SetErrorMode(0);
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    return NULL;
}

/*
 * Return a Python dict of tuples for disk I/O information
 */
static PyObject *
psutil_users(PyObject *self, PyObject *args) {
    HANDLE hServer = WTS_CURRENT_SERVER_HANDLE;
    LPTSTR buffer_user = NULL;
    LPTSTR buffer_addr = NULL;
    PWTS_SESSION_INFO sessions = NULL;
    DWORD count;
    DWORD i;
    DWORD sessionId;
    DWORD bytes;
    PWTS_CLIENT_ADDRESS address;
    char address_str[50];
    long long unix_time;

    PWINSTATIONQUERYINFORMATIONW WinStationQueryInformationW;
    WINSTATION_INFO station_info;
    HINSTANCE hInstWinSta = NULL;
    ULONG returnLen;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_address = NULL;
    PyObject *py_buffer_user_encoded = NULL;

    if (py_retlist == NULL)
        return NULL;

    hInstWinSta = LoadLibraryA("winsta.dll");
    WinStationQueryInformationW = (PWINSTATIONQUERYINFORMATIONW) \
        GetProcAddress(hInstWinSta, "WinStationQueryInformationW");

    if (WTSEnumerateSessions(hServer, 0, 1, &sessions, &count) == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    for (i = 0; i < count; i++) {
        py_address = NULL;
        py_tuple = NULL;
        sessionId = sessions[i].SessionId;
        if (buffer_user != NULL)
            WTSFreeMemory(buffer_user);
        if (buffer_addr != NULL)
            WTSFreeMemory(buffer_addr);

        buffer_user = NULL;
        buffer_addr = NULL;

        // username
        bytes = 0;
        if (WTSQuerySessionInformation(hServer, sessionId, WTSUserName,
                                       &buffer_user, &bytes) == 0) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }
        if (bytes == 1)
            continue;

        // address
        bytes = 0;
        if (WTSQuerySessionInformation(hServer, sessionId, WTSClientAddress,
                                       &buffer_addr, &bytes) == 0) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        address = (PWTS_CLIENT_ADDRESS)buffer_addr;
        if (address->AddressFamily == 0) {  // AF_INET
            sprintf_s(address_str,
                      _countof(address_str),
                      "%u.%u.%u.%u",
                      address->Address[0],
                      address->Address[1],
                      address->Address[2],
                      address->Address[3]);
            py_address = Py_BuildValue("s", address_str);
            if (!py_address)
                goto error;
        }
        else {
            py_address = Py_None;
        }

        // login time
        if (!WinStationQueryInformationW(hServer,
                                         sessionId,
                                         WinStationInformation,
                                         &station_info,
                                         sizeof(station_info),
                                         &returnLen))
        {
            goto error;
        }

        unix_time = ((LONGLONG)station_info.ConnectTime.dwHighDateTime) << 32;
        unix_time += \
            station_info.ConnectTime.dwLowDateTime - 116444736000000000LL;
        unix_time /= 10000000;

#if PY_MAJOR_VERSION >= 3 && PY_MINOR_VERSION >= 3
        py_buffer_user_encoded = PyUnicode_DecodeLocaleAndSize(
            buffer_user, _tcslen(buffer_user), "surrogateescape");
#else
        py_buffer_user_encoded = PyUnicode_Decode(
            buffer_user, _tcslen(buffer_user), Py_FileSystemDefaultEncoding,
            "replace");
#endif

        if (py_buffer_user_encoded == NULL)
            goto error;
        py_tuple = Py_BuildValue("OOd", py_buffer_user_encoded, py_address,
                                 (double)unix_time);
        if (!py_tuple)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_XDECREF(py_buffer_user_encoded);
        Py_XDECREF(py_address);
        Py_XDECREF(py_tuple);
    }

    WTSFreeMemory(sessions);
    WTSFreeMemory(buffer_user);
    WTSFreeMemory(buffer_addr);
    FreeLibrary(hInstWinSta);
    return py_retlist;

error:
    Py_XDECREF(py_buffer_user_encoded);
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_address);
    Py_DECREF(py_retlist);

    if (hInstWinSta != NULL)
        FreeLibrary(hInstWinSta);
    if (sessions != NULL)
        WTSFreeMemory(sessions);
    if (buffer_user != NULL)
        WTSFreeMemory(buffer_user);
    if (buffer_addr != NULL)
        WTSFreeMemory(buffer_addr);
    return NULL;
}


/*
 * Return the number of handles opened by process.
 */
static PyObject *
psutil_proc_num_handles(PyObject *self, PyObject *args) {
    DWORD pid;
    HANDLE hProcess;
    DWORD handleCount;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    hProcess = psutil_handle_from_pid(pid);
    if (NULL == hProcess)
        return NULL;
    if (! GetProcessHandleCount(hProcess, &handleCount)) {
        CloseHandle(hProcess);
        return PyErr_SetFromWindowsErr(0);
    }
    CloseHandle(hProcess);
    return Py_BuildValue("k", handleCount);
}


/*
 * Get various process information by using NtQuerySystemInformation.
 * We use this as a fallback when faster functions fail with access
 * denied. This is slower because it iterates over all processes.
 * Returned tuple includes the following process info:
 *
 * - num_threads()
 * - ctx_switches()
 * - num_handles() (fallback)
 * - cpu_times() (fallback)
 * - create_time() (fallback)
 * - io_counters() (fallback)
 * - memory_info() (fallback)
 */
static PyObject *
psutil_proc_info(PyObject *self, PyObject *args) {
    DWORD pid;
    PSYSTEM_PROCESS_INFORMATION process;
    PVOID buffer;
    ULONG i;
    ULONG ctx_switches = 0;
    double user_time;
    double kernel_time;
    long long create_time;
    SIZE_T mem_private;
    PyObject *py_retlist;

    if (! PyArg_ParseTuple(args, "l", &pid))
        return NULL;
    if (! psutil_get_proc_info(pid, &process, &buffer))
        return NULL;

    for (i = 0; i < process->NumberOfThreads; i++)
        ctx_switches += process->Threads[i].ContextSwitches;
    user_time = (double)process->UserTime.HighPart * 429.4967296 + \
                (double)process->UserTime.LowPart * 1e-7;
    kernel_time = (double)process->KernelTime.HighPart * 429.4967296 + \
                  (double)process->KernelTime.LowPart * 1e-7;
    // Convert the LARGE_INTEGER union to a Unix time.
    // It's the best I could find by googling and borrowing code here
    // and there. The time returned has a precision of 1 second.
    if (0 == pid || 4 == pid) {
        // the python module will translate this into BOOT_TIME later
        create_time = 0;
    }
    else {
        create_time = ((LONGLONG)process->CreateTime.HighPart) << 32;
        create_time += process->CreateTime.LowPart - 116444736000000000LL;
        create_time /= 10000000;
    }

#if (_WIN32_WINNT >= 0x0501)  // Windows XP with SP2
    mem_private = process->PrivatePageCount;
#else
    mem_private = 0;
#endif

    py_retlist = Py_BuildValue(
#if defined(_WIN64)
        "kkdddiKKKKKK" "kKKKKKKKKK",
#else
        "kkdddiKKKKKK" "kIIIIIIIII",
#endif
        process->HandleCount,                   // num handles
        ctx_switches,                           // num ctx switches
        user_time,                              // cpu user time
        kernel_time,                            // cpu kernel time
        (double)create_time,                    // create time
        (int)process->NumberOfThreads,          // num threads
        // IO counters
        process->ReadOperationCount.QuadPart,   // io rcount
        process->WriteOperationCount.QuadPart,  // io wcount
        process->ReadTransferCount.QuadPart,    // io rbytes
        process->WriteTransferCount.QuadPart,   // io wbytes
        process->OtherOperationCount.QuadPart,  // io others count
        process->OtherTransferCount.QuadPart,   // io others bytes
        // memory
        process->PageFaultCount,                // num page faults
        process->PeakWorkingSetSize,            // peak wset
        process->WorkingSetSize,                // wset
        process->QuotaPeakPagedPoolUsage,       // peak paged pool
        process->QuotaPagedPoolUsage,           // paged pool
        process->QuotaPeakNonPagedPoolUsage,    // peak non paged pool
        process->QuotaNonPagedPoolUsage,        // non paged pool
        process->PagefileUsage,                 // pagefile
        process->PeakPagefileUsage,             // peak pagefile
        mem_private                             // private
    );

    free(buffer);
    return py_retlist;
}


static char *get_region_protection_string(ULONG protection) {
    switch (protection & 0xff) {
        case PAGE_NOACCESS:
            return "";
        case PAGE_READONLY:
            return "r";
        case PAGE_READWRITE:
            return "rw";
        case PAGE_WRITECOPY:
            return "wc";
        case PAGE_EXECUTE:
            return "x";
        case PAGE_EXECUTE_READ:
            return "xr";
        case PAGE_EXECUTE_READWRITE:
            return "xrw";
        case PAGE_EXECUTE_WRITECOPY:
            return "xwc";
        default:
            return "?";
    }
}


/*
 * Return a list of process's memory mappings.
 */
static PyObject *
psutil_proc_memory_maps(PyObject *self, PyObject *args) {
#ifdef _WIN64
    MEMORY_BASIC_INFORMATION64 basicInfo;
#else
    MEMORY_BASIC_INFORMATION basicInfo;
#endif
    DWORD pid;
    HANDLE hProcess = NULL;
    PVOID baseAddress;
    PVOID previousAllocationBase;
    CHAR mappedFileName[MAX_PATH];
    SYSTEM_INFO system_info;
    LPVOID maxAddr;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;

    if (py_retlist == NULL)
        return NULL;
    if (! PyArg_ParseTuple(args, "l", &pid))
        goto error;
    hProcess = psutil_handle_from_pid(pid);
    if (NULL == hProcess)
        goto error;

    GetSystemInfo(&system_info);
    maxAddr = system_info.lpMaximumApplicationAddress;
    baseAddress = NULL;
    previousAllocationBase = NULL;

    while (VirtualQueryEx(hProcess, baseAddress, &basicInfo,
                          sizeof(MEMORY_BASIC_INFORMATION)))
    {
        py_tuple = NULL;
        if (baseAddress > maxAddr)
            break;
        if (GetMappedFileNameA(hProcess, baseAddress, mappedFileName,
                               sizeof(mappedFileName)))
        {
#ifdef _WIN64
           py_tuple = Py_BuildValue(
              "(KssI)",
              (unsigned long long)baseAddress,
#else
           py_tuple = Py_BuildValue(
              "(kssI)",
              (unsigned long)baseAddress,
#endif
              get_region_protection_string(basicInfo.Protect),
              mappedFileName,
              basicInfo.RegionSize);

            if (!py_tuple)
                goto error;
            if (PyList_Append(py_retlist, py_tuple))
                goto error;
            Py_DECREF(py_tuple);
        }
        previousAllocationBase = basicInfo.AllocationBase;
        baseAddress = (PCHAR)baseAddress + basicInfo.RegionSize;
    }

    CloseHandle(hProcess);
    return py_retlist;

error:
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (hProcess != NULL)
        CloseHandle(hProcess);
    return NULL;
}


/*
 * Return a {pid:ppid, ...} dict for all running processes.
 */
static PyObject *
psutil_ppid_map(PyObject *self, PyObject *args) {
    PyObject *py_pid = NULL;
    PyObject *py_ppid = NULL;
    PyObject *py_retdict = PyDict_New();
    HANDLE handle = NULL;
    PROCESSENTRY32 pe = {0};
    pe.dwSize = sizeof(PROCESSENTRY32);

    if (py_retdict == NULL)
        return NULL;
    handle = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (handle == INVALID_HANDLE_VALUE) {
        PyErr_SetFromWindowsErr(0);
        Py_DECREF(py_retdict);
        return NULL;
    }

    if (Process32First(handle, &pe)) {
        do {
            py_pid = Py_BuildValue("I", pe.th32ProcessID);
            if (py_pid == NULL)
                goto error;
            py_ppid = Py_BuildValue("I", pe.th32ParentProcessID);
            if (py_ppid == NULL)
                goto error;
            if (PyDict_SetItem(py_retdict, py_pid, py_ppid))
                goto error;
            Py_DECREF(py_pid);
            Py_DECREF(py_ppid);
        } while (Process32Next(handle, &pe));
    }

    CloseHandle(handle);
    return py_retdict;

error:
    Py_XDECREF(py_pid);
    Py_XDECREF(py_ppid);
    Py_DECREF(py_retdict);
    CloseHandle(handle);
    return NULL;
}


/*
 * Return NICs addresses.
 */

static PyObject *
psutil_net_if_addrs(PyObject *self, PyObject *args) {
    unsigned int i = 0;
    ULONG family;
    PCTSTR intRet;
    PCTSTR netmaskIntRet;
    char *ptr;
    char buff[100];
    DWORD bufflen = 100;
    char netmask_buff[100];
    DWORD netmask_bufflen = 100;
    DWORD dwRetVal = 0;
#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
    ULONG converted_netmask;
    UINT netmask_bits;
    struct in_addr in_netmask;
#endif
    PIP_ADAPTER_ADDRESSES pAddresses = NULL;
    PIP_ADAPTER_ADDRESSES pCurrAddresses = NULL;
    PIP_ADAPTER_UNICAST_ADDRESS pUnicast = NULL;

    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_address = NULL;
    PyObject *py_mac_address = NULL;
    PyObject *py_nic_name = NULL;
    PyObject *py_netmask = NULL;

    if (py_retlist == NULL)
        return NULL;

    pAddresses = psutil_get_nic_addresses();
    if (pAddresses == NULL)
        goto error;
    pCurrAddresses = pAddresses;

    while (pCurrAddresses) {
        pUnicast = pCurrAddresses->FirstUnicastAddress;

        netmaskIntRet = NULL;
        py_nic_name = NULL;
        py_nic_name = PyUnicode_FromWideChar(
            pCurrAddresses->FriendlyName,
            wcslen(pCurrAddresses->FriendlyName));
        if (py_nic_name == NULL)
            goto error;

        // MAC address
        if (pCurrAddresses->PhysicalAddressLength != 0) {
            ptr = buff;
            *ptr = '\0';
            for (i = 0; i < (int) pCurrAddresses->PhysicalAddressLength; i++) {
                if (i == (pCurrAddresses->PhysicalAddressLength - 1)) {
                    sprintf_s(ptr, _countof(buff), "%.2X\n",
                            (int)pCurrAddresses->PhysicalAddress[i]);
                }
                else {
                    sprintf_s(ptr, _countof(buff), "%.2X-",
                            (int)pCurrAddresses->PhysicalAddress[i]);
                }
                ptr += 3;
            }
            *--ptr = '\0';

#if PY_MAJOR_VERSION >= 3
            py_mac_address = PyUnicode_FromString(buff);
#else
            py_mac_address = PyString_FromString(buff);
#endif
            if (py_mac_address == NULL)
                goto error;

            Py_INCREF(Py_None);
            Py_INCREF(Py_None);
            Py_INCREF(Py_None);
            py_tuple = Py_BuildValue(
                "(OiOOOO)",
                py_nic_name,
                -1,  // this will be converted later to AF_LINK
                py_mac_address,
                Py_None,  // netmask (not supported)
                Py_None,  // broadcast (not supported)
                Py_None  // ptp (not supported on Windows)
            );
            if (! py_tuple)
                goto error;
            if (PyList_Append(py_retlist, py_tuple))
                goto error;
            Py_DECREF(py_tuple);
            Py_DECREF(py_mac_address);
        }

        // find out the IP address associated with the NIC
        if (pUnicast != NULL) {
            for (i = 0; pUnicast != NULL; i++) {
                family = pUnicast->Address.lpSockaddr->sa_family;
                if (family == AF_INET) {
                    struct sockaddr_in *sa_in = (struct sockaddr_in *)
                        pUnicast->Address.lpSockaddr;
                    intRet = inet_ntop(AF_INET, &(sa_in->sin_addr), buff,
                                       bufflen);
#if (_WIN32_WINNT >= 0x0600) // Windows Vista and above
                    netmask_bits = pUnicast->OnLinkPrefixLength;
                    dwRetVal = ConvertLengthToIpv4Mask(netmask_bits, &converted_netmask);
                    if (dwRetVal == NO_ERROR) {
                        in_netmask.s_addr = converted_netmask;
                        netmaskIntRet = inet_ntop(AF_INET, &in_netmask, netmask_buff,
                                                  netmask_bufflen);
                    }
#endif
                }
                else if (family == AF_INET6) {
                    struct sockaddr_in6 *sa_in6 = (struct sockaddr_in6 *)
                        pUnicast->Address.lpSockaddr;
                    intRet = inet_ntop(AF_INET6, &(sa_in6->sin6_addr),
                                       buff, bufflen);
                }
                else {
                    // we should never get here
                    pUnicast = pUnicast->Next;
                    continue;
                }

                if (intRet == NULL) {
                    PyErr_SetFromWindowsErr(GetLastError());
                    goto error;
                }
#if PY_MAJOR_VERSION >= 3
                py_address = PyUnicode_FromString(buff);
#else
                py_address = PyString_FromString(buff);
#endif
                if (py_address == NULL)
                    goto error;

                if (netmaskIntRet != NULL) {
#if PY_MAJOR_VERSION >= 3
                    py_netmask = PyUnicode_FromString(netmask_buff);
#else
                    py_netmask = PyString_FromString(netmask_buff);
#endif
                } else {
                    Py_INCREF(Py_None);
                    py_netmask = Py_None;
                }

                Py_INCREF(Py_None);
                Py_INCREF(Py_None);
                py_tuple = Py_BuildValue(
                    "(OiOOOO)",
                    py_nic_name,
                    family,
                    py_address,
                    py_netmask,
                    Py_None,  // broadcast (not supported)
                    Py_None  // ptp (not supported on Windows)
                );

                if (! py_tuple)
                    goto error;
                if (PyList_Append(py_retlist, py_tuple))
                    goto error;
                Py_DECREF(py_tuple);
                Py_DECREF(py_address);
                Py_DECREF(py_netmask);

                pUnicast = pUnicast->Next;
            }
        }
        Py_DECREF(py_nic_name);
        pCurrAddresses = pCurrAddresses->Next;
    }

    free(pAddresses);
    return py_retlist;

error:
    if (pAddresses)
        free(pAddresses);
    Py_DECREF(py_retlist);
    Py_XDECREF(py_tuple);
    Py_XDECREF(py_address);
    Py_XDECREF(py_nic_name);
    Py_XDECREF(py_netmask);
    return NULL;
}


/*
 * Provides stats about NIC interfaces installed on the system.
 * TODO: get 'duplex' (currently it's hard coded to '2', aka
         'full duplex')
 */
static PyObject *
psutil_net_if_stats(PyObject *self, PyObject *args) {
    int i;
    DWORD dwSize = 0;
    DWORD dwRetVal = 0;
    MIB_IFTABLE *pIfTable;
    MIB_IFROW *pIfRow;
    PIP_ADAPTER_ADDRESSES pAddresses = NULL;
    PIP_ADAPTER_ADDRESSES pCurrAddresses = NULL;
    char descr[MAX_PATH];
    int ifname_found;

    PyObject *py_nic_name = NULL;
    PyObject *py_retdict = PyDict_New();
    PyObject *py_ifc_info = NULL;
    PyObject *py_is_up = NULL;

    if (py_retdict == NULL)
        return NULL;

    pAddresses = psutil_get_nic_addresses();
    if (pAddresses == NULL)
        goto error;

    pIfTable = (MIB_IFTABLE *) malloc(sizeof (MIB_IFTABLE));
    if (pIfTable == NULL) {
        PyErr_NoMemory();
        goto error;
    }
    dwSize = sizeof(MIB_IFTABLE);
    if (GetIfTable(pIfTable, &dwSize, FALSE) == ERROR_INSUFFICIENT_BUFFER) {
        free(pIfTable);
        pIfTable = (MIB_IFTABLE *) malloc(dwSize);
        if (pIfTable == NULL) {
            PyErr_NoMemory();
            goto error;
        }
    }
    // Make a second call to GetIfTable to get the actual
    // data we want.
    if ((dwRetVal = GetIfTable(pIfTable, &dwSize, FALSE)) != NO_ERROR) {
        PyErr_SetString(PyExc_RuntimeError, "GetIfTable() syscall failed");
        goto error;
    }

    for (i = 0; i < (int) pIfTable->dwNumEntries; i++) {
        pIfRow = (MIB_IFROW *) & pIfTable->table[i];

        // GetIfTable is not able to give us NIC with "friendly names"
        // so we determine them via GetAdapterAddresses() which
        // provides friendly names *and* descriptions and find the
        // ones that match.
        ifname_found = 0;
        pCurrAddresses = pAddresses;
        while (pCurrAddresses) {
            sprintf_s(descr, MAX_PATH, "%wS", pCurrAddresses->Description);
            if (lstrcmp(descr, pIfRow->bDescr) == 0) {
                py_nic_name = PyUnicode_FromWideChar(
                    pCurrAddresses->FriendlyName,
                    wcslen(pCurrAddresses->FriendlyName));
                if (py_nic_name == NULL)
                    goto error;
                ifname_found = 1;
                break;
            }
            pCurrAddresses = pCurrAddresses->Next;
        }
        if (ifname_found == 0) {
            // Name not found means GetAdapterAddresses() doesn't list
            // this NIC, only GetIfTable, meaning it's not really a NIC
            // interface so we skip it.
            continue;
        }

        // is up?
        if((pIfRow->dwOperStatus == MIB_IF_OPER_STATUS_CONNECTED ||
                pIfRow->dwOperStatus == MIB_IF_OPER_STATUS_OPERATIONAL) &&
                pIfRow->dwAdminStatus == 1 ) {
            py_is_up = Py_True;
        }
        else {
            py_is_up = Py_False;
        }
        Py_INCREF(py_is_up);

        py_ifc_info = Py_BuildValue(
            "(Oikk)",
            py_is_up,
            2,  // there's no way to know duplex so let's assume 'full'
            pIfRow->dwSpeed / 1000000,  // expressed in bytes, we want Mb
            pIfRow->dwMtu
        );
        if (!py_ifc_info)
            goto error;
        if (PyDict_SetItem(py_retdict, py_nic_name, py_ifc_info))
            goto error;
        Py_DECREF(py_nic_name);
        Py_DECREF(py_ifc_info);
    }

    free(pIfTable);
    free(pAddresses);
    return py_retdict;

error:
    Py_XDECREF(py_is_up);
    Py_XDECREF(py_ifc_info);
    Py_XDECREF(py_nic_name);
    Py_DECREF(py_retdict);
    if (pIfTable != NULL)
        free(pIfTable);
    if (pAddresses != NULL)
        free(pAddresses);
    return NULL;
}


/*
 * Return CPU statistics.
 */
static PyObject *
psutil_cpu_stats(PyObject *self, PyObject *args) {
    // NtQuerySystemInformation stuff
    typedef DWORD (_stdcall * NTQSI_PROC) (int, PVOID, ULONG, PULONG);
    NTQSI_PROC NtQuerySystemInformation;
    HINSTANCE hNtDll;

    NTSTATUS status;
    _SYSTEM_PERFORMANCE_INFORMATION *spi = NULL;
    _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION *sppi = NULL;
    _SYSTEM_INTERRUPT_INFORMATION *InterruptInformation = NULL;
    SYSTEM_INFO si;
    UINT i;
    ULONG64 dpcs = 0;
    ULONG interrupts = 0;

    // obtain NtQuerySystemInformation
    hNtDll = LoadLibrary(TEXT("ntdll.dll"));
    if (hNtDll == NULL) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }
    NtQuerySystemInformation = (NTQSI_PROC)GetProcAddress(
        hNtDll, "NtQuerySystemInformation");
    if (NtQuerySystemInformation == NULL) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // retrives number of processors
    GetSystemInfo(&si);

    // get syscalls / ctx switches
    spi = (_SYSTEM_PERFORMANCE_INFORMATION *) \
           malloc(si.dwNumberOfProcessors * \
                  sizeof(_SYSTEM_PERFORMANCE_INFORMATION));
    if (spi == NULL) {
        PyErr_NoMemory();
        goto error;
    }
    status = NtQuerySystemInformation(
        SystemPerformanceInformation,
        spi,
        si.dwNumberOfProcessors * sizeof(_SYSTEM_PERFORMANCE_INFORMATION),
        NULL);
    if (status != 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // get DPCs
    InterruptInformation = \
        malloc(sizeof(_SYSTEM_INTERRUPT_INFORMATION) *
               si.dwNumberOfProcessors);
    if (InterruptInformation == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    status = NtQuerySystemInformation(
        SystemInterruptInformation,
        InterruptInformation,
        si.dwNumberOfProcessors * sizeof(SYSTEM_INTERRUPT_INFORMATION),
        NULL);
    if (status != 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }
    for (i = 0; i < si.dwNumberOfProcessors; i++) {
        dpcs += InterruptInformation[i].DpcCount;
    }

    // get interrupts
    sppi = (_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION *) \
        malloc(si.dwNumberOfProcessors * \
               sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION));
    if (sppi == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    status = NtQuerySystemInformation(
        SystemProcessorPerformanceInformation,
        sppi,
        si.dwNumberOfProcessors * sizeof
            (_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION),
        NULL);
    if (status != 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    for (i = 0; i < si.dwNumberOfProcessors; i++) {
        interrupts += sppi[i].InterruptCount;
    }

    // done
    free(spi);
    free(InterruptInformation);
    free(sppi);
    FreeLibrary(hNtDll);
    return Py_BuildValue(
        "kkkk",
        spi->ContextSwitches,
        interrupts,
        (unsigned long)dpcs,
        spi->SystemCalls
    );

error:
    if (spi)
        free(spi);
    if (InterruptInformation)
        free(InterruptInformation);
    if (sppi)
        free(sppi);
    if (hNtDll)
        FreeLibrary(hNtDll);
    return NULL;
}


/*
 * Return CPU frequency.
 */
static PyObject *
psutil_cpu_freq(PyObject *self, PyObject *args) {
    PROCESSOR_POWER_INFORMATION *ppi;
    NTSTATUS ret;
    size_t size;
    LPBYTE pBuffer = NULL;
    ULONG current;
    ULONG max;
    unsigned int num_cpus;
    SYSTEM_INFO system_info;
    system_info.dwNumberOfProcessors = 0;

    // Get the number of CPUs.
    GetSystemInfo(&system_info);
    if (system_info.dwNumberOfProcessors == 0)
        num_cpus = 1;
    else
        num_cpus = system_info.dwNumberOfProcessors;

    // Allocate size.
    size = num_cpus * sizeof(PROCESSOR_POWER_INFORMATION);
    pBuffer = (BYTE*)LocalAlloc(LPTR, size);
    if (! pBuffer) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }

    // Syscall.
    ret = CallNtPowerInformation(
        ProcessorInformation, NULL, 0, pBuffer, size);
    if (ret != 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "CallNtPowerInformation syscall failed");
        goto error;
    }

    // Results.
    ppi = (PROCESSOR_POWER_INFORMATION *)pBuffer;
    max = ppi->MaxMhz;
    current = ppi->CurrentMhz;
    LocalFree(pBuffer);

    return Py_BuildValue("kk", current, max);

error:
    if (pBuffer != NULL)
        LocalFree(pBuffer);
    return NULL;
}


/*
 * Return battery usage stats.
 */
static PyObject *
psutil_sensors_battery(PyObject *self, PyObject *args) {
    SYSTEM_POWER_STATUS sps;

    if (GetSystemPowerStatus(&sps) == 0) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    return Py_BuildValue(
        "iiiI",
        sps.ACLineStatus,  // whether AC is connected: 0=no, 1=yes, 255=unknown
        // status flag:
        // 1, 2, 4 = high, low, critical
        // 8 = charging
        // 128 = no battery
        sps.BatteryFlag,
        sps.BatteryLifePercent,  // percent
        sps.BatteryLifeTime  // remaining secs
    );
}


// ------------------------ Python init ---------------------------

static PyMethodDef
PsutilMethods[] = {

    // --- per-process functions

    {"proc_cmdline", psutil_proc_cmdline, METH_VARARGS,
     "Return process cmdline as a list of cmdline arguments"},
    {"proc_environ", psutil_proc_environ, METH_VARARGS,
     "Return process environment data"},
    {"proc_exe", psutil_proc_exe, METH_VARARGS,
     "Return path of the process executable"},
    {"proc_name", psutil_proc_name, METH_VARARGS,
     "Return process name"},
    {"proc_kill", psutil_proc_kill, METH_VARARGS,
     "Kill the process identified by the given PID"},
    {"proc_cpu_times", psutil_proc_cpu_times, METH_VARARGS,
     "Return tuple of user/kern time for the given PID"},
    {"proc_create_time", psutil_proc_create_time, METH_VARARGS,
     "Return a float indicating the process create time expressed in "
     "seconds since the epoch"},
    {"proc_memory_info", psutil_proc_memory_info, METH_VARARGS,
     "Return a tuple of process memory information"},
    {"proc_memory_uss", psutil_proc_memory_uss, METH_VARARGS,
     "Return the USS of the process"},
    {"proc_cwd", psutil_proc_cwd, METH_VARARGS,
     "Return process current working directory"},
    {"proc_suspend", psutil_proc_suspend, METH_VARARGS,
     "Suspend a process"},
    {"proc_resume", psutil_proc_resume, METH_VARARGS,
     "Resume a process"},
    {"proc_open_files", psutil_proc_open_files, METH_VARARGS,
     "Return files opened by process"},
    {"proc_username", psutil_proc_username, METH_VARARGS,
     "Return the username of a process"},
    {"proc_threads", psutil_proc_threads, METH_VARARGS,
     "Return process threads information as a list of tuple"},
    {"proc_wait", psutil_proc_wait, METH_VARARGS,
     "Wait for process to terminate and return its exit code."},
    {"proc_priority_get", psutil_proc_priority_get, METH_VARARGS,
     "Return process priority."},
    {"proc_priority_set", psutil_proc_priority_set, METH_VARARGS,
     "Set process priority."},
#if (_WIN32_WINNT >= 0x0600)  // Windows Vista
    {"proc_io_priority_get", psutil_proc_io_priority_get, METH_VARARGS,
     "Return process IO priority."},
    {"proc_io_priority_set", psutil_proc_io_priority_set, METH_VARARGS,
     "Set process IO priority."},
#endif
    {"proc_cpu_affinity_get", psutil_proc_cpu_affinity_get, METH_VARARGS,
     "Return process CPU affinity as a bitmask."},
    {"proc_cpu_affinity_set", psutil_proc_cpu_affinity_set, METH_VARARGS,
     "Set process CPU affinity."},
    {"proc_io_counters", psutil_proc_io_counters, METH_VARARGS,
     "Get process I/O counters."},
    {"proc_is_suspended", psutil_proc_is_suspended, METH_VARARGS,
     "Return True if one of the process threads is in a suspended state"},
    {"proc_num_handles", psutil_proc_num_handles, METH_VARARGS,
     "Return the number of handles opened by process."},
    {"proc_memory_maps", psutil_proc_memory_maps, METH_VARARGS,
     "Return a list of process's memory mappings"},

    // --- alternative pinfo interface
    {"proc_info", psutil_proc_info, METH_VARARGS,
     "Various process information"},

    // --- system-related functions
    {"pids", psutil_pids, METH_VARARGS,
     "Returns a list of PIDs currently running on the system"},
    {"ppid_map", psutil_ppid_map, METH_VARARGS,
     "Return a {pid:ppid, ...} dict for all running processes"},
    {"pid_exists", psutil_pid_exists, METH_VARARGS,
     "Determine if the process exists in the current process list."},
    {"cpu_count_logical", psutil_cpu_count_logical, METH_VARARGS,
     "Returns the number of logical CPUs on the system"},
    {"cpu_count_phys", psutil_cpu_count_phys, METH_VARARGS,
     "Returns the number of physical CPUs on the system"},
    {"boot_time", psutil_boot_time, METH_VARARGS,
     "Return the system boot time expressed in seconds since the epoch."},
    {"virtual_mem", psutil_virtual_mem, METH_VARARGS,
     "Return the total amount of physical memory, in bytes"},
    {"cpu_times", psutil_cpu_times, METH_VARARGS,
     "Return system cpu times as a list"},
    {"per_cpu_times", psutil_per_cpu_times, METH_VARARGS,
     "Return system per-cpu times as a list of tuples"},
    {"disk_usage", psutil_disk_usage, METH_VARARGS,
     "Return path's disk total and free as a Python tuple."},
    {"net_io_counters", psutil_net_io_counters, METH_VARARGS,
     "Return dict of tuples of networks I/O information."},
    {"disk_io_counters", psutil_disk_io_counters, METH_VARARGS,
     "Return dict of tuples of disks I/O information."},
    {"users", psutil_users, METH_VARARGS,
     "Return a list of currently connected users."},
    {"disk_partitions", psutil_disk_partitions, METH_VARARGS,
     "Return disk partitions."},
    {"net_connections", psutil_net_connections, METH_VARARGS,
     "Return system-wide connections"},
    {"net_if_addrs", psutil_net_if_addrs, METH_VARARGS,
     "Return NICs addresses."},
    {"net_if_stats", psutil_net_if_stats, METH_VARARGS,
     "Return NICs stats."},
    {"cpu_stats", psutil_cpu_stats, METH_VARARGS,
     "Return NICs stats."},
    {"cpu_freq", psutil_cpu_freq, METH_VARARGS,
     "Return CPU frequency."},
    {"sensors_battery", psutil_sensors_battery, METH_VARARGS,
     "Return battery metrics usage."},

    // --- windows services
    {"winservice_enumerate", psutil_winservice_enumerate, METH_VARARGS,
     "List all services"},
    {"winservice_query_config", psutil_winservice_query_config, METH_VARARGS,
     "Return service config"},
    {"winservice_query_status", psutil_winservice_query_status, METH_VARARGS,
     "Return service config"},
    {"winservice_query_descr", psutil_winservice_query_descr, METH_VARARGS,
     "Return the description of a service"},
    {"winservice_start", psutil_winservice_start, METH_VARARGS,
     "Start a service"},
    {"winservice_stop", psutil_winservice_stop, METH_VARARGS,
     "Stop a service"},

    // --- windows API bindings
    {"win32_QueryDosDevice", psutil_win32_QueryDosDevice, METH_VARARGS,
     "QueryDosDevice binding"},

    {NULL, NULL, 0, NULL}
};


struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
#define GETSTATE(m) (&_state)
static struct module_state _state;
#endif

#if PY_MAJOR_VERSION >= 3

static int psutil_windows_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int psutil_windows_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "psutil_windows",
    NULL,
    sizeof(struct module_state),
    PsutilMethods,
    NULL,
    psutil_windows_traverse,
    psutil_windows_clear,
    NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit__psutil_windows(void)

#else
#define INITERROR return
void init_psutil_windows(void)
#endif
{
    struct module_state *st = NULL;
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("_psutil_windows", PsutilMethods);
#endif

    if (module == NULL) {
        INITERROR;
    }

    st = GETSTATE(module);
    st->error = PyErr_NewException("_psutil_windows.Error", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    PyModule_AddIntConstant(module, "version", PSUTIL_VERSION);

    // process status constants
    // http://msdn.microsoft.com/en-us/library/ms683211(v=vs.85).aspx
    PyModule_AddIntConstant(
        module, "ABOVE_NORMAL_PRIORITY_CLASS", ABOVE_NORMAL_PRIORITY_CLASS);
    PyModule_AddIntConstant(
        module, "BELOW_NORMAL_PRIORITY_CLASS", BELOW_NORMAL_PRIORITY_CLASS);
    PyModule_AddIntConstant(
        module, "HIGH_PRIORITY_CLASS", HIGH_PRIORITY_CLASS);
    PyModule_AddIntConstant(
        module, "IDLE_PRIORITY_CLASS", IDLE_PRIORITY_CLASS);
    PyModule_AddIntConstant(
        module, "NORMAL_PRIORITY_CLASS", NORMAL_PRIORITY_CLASS);
    PyModule_AddIntConstant(
        module, "REALTIME_PRIORITY_CLASS", REALTIME_PRIORITY_CLASS);

    // connection status constants
    // http://msdn.microsoft.com/en-us/library/cc669305.aspx
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_CLOSED", MIB_TCP_STATE_CLOSED);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_CLOSING", MIB_TCP_STATE_CLOSING);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_CLOSE_WAIT", MIB_TCP_STATE_CLOSE_WAIT);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_LISTEN", MIB_TCP_STATE_LISTEN);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_ESTAB", MIB_TCP_STATE_ESTAB);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_SYN_SENT", MIB_TCP_STATE_SYN_SENT);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_SYN_RCVD", MIB_TCP_STATE_SYN_RCVD);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_FIN_WAIT1", MIB_TCP_STATE_FIN_WAIT1);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_FIN_WAIT2", MIB_TCP_STATE_FIN_WAIT2);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_LAST_ACK", MIB_TCP_STATE_LAST_ACK);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_TIME_WAIT", MIB_TCP_STATE_TIME_WAIT);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_TIME_WAIT", MIB_TCP_STATE_TIME_WAIT);
    PyModule_AddIntConstant(
        module, "MIB_TCP_STATE_DELETE_TCB", MIB_TCP_STATE_DELETE_TCB);
    PyModule_AddIntConstant(
        module, "PSUTIL_CONN_NONE", PSUTIL_CONN_NONE);

    // service status constants
    /*
    PyModule_AddIntConstant(
        module, "SERVICE_CONTINUE_PENDING", SERVICE_CONTINUE_PENDING);
    PyModule_AddIntConstant(
        module, "SERVICE_PAUSE_PENDING", SERVICE_PAUSE_PENDING);
    PyModule_AddIntConstant(
        module, "SERVICE_PAUSED", SERVICE_PAUSED);
    PyModule_AddIntConstant(
        module, "SERVICE_RUNNING", SERVICE_RUNNING);
    PyModule_AddIntConstant(
        module, "SERVICE_START_PENDING", SERVICE_START_PENDING);
    PyModule_AddIntConstant(
        module, "SERVICE_STOP_PENDING", SERVICE_STOP_PENDING);
    PyModule_AddIntConstant(
        module, "SERVICE_STOPPED", SERVICE_STOPPED);
    */

    // ...for internal use in _psutil_windows.py
    PyModule_AddIntConstant(
        module, "INFINITE", INFINITE);
    PyModule_AddIntConstant(
        module, "ERROR_ACCESS_DENIED", ERROR_ACCESS_DENIED);
    PyModule_AddIntConstant(
        module, "ERROR_INVALID_NAME", ERROR_INVALID_NAME);
    PyModule_AddIntConstant(
        module, "ERROR_SERVICE_DOES_NOT_EXIST", ERROR_SERVICE_DOES_NOT_EXIST);

    // set SeDebug for the current process
    psutil_set_se_debug();

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
