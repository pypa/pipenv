/*
 * Copyright (c) 2009, Jay Loden, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Helper functions related to fetching process information. Used by
 * _psutil_windows module methods.
 */

#include <Python.h>
#include <windows.h>
#include <Psapi.h>
#include <tlhelp32.h>

#include "security.h"
#include "process_info.h"
#include "ntextapi.h"
#include "../../_psutil_common.h"


/*
 * A wrapper around OpenProcess setting NSP exception if process
 * no longer exists.
 * "pid" is the process pid, "dwDesiredAccess" is the first argument
 * exptected by OpenProcess.
 * Return a process handle or NULL.
 */
HANDLE
psutil_handle_from_pid_waccess(DWORD pid, DWORD dwDesiredAccess) {
    HANDLE hProcess;
    DWORD processExitCode = 0;

    if (pid == 0) {
        // otherwise we'd get NoSuchProcess
        return AccessDenied();
    }

    hProcess = OpenProcess(dwDesiredAccess, FALSE, pid);
    if (hProcess == NULL) {
        if (GetLastError() == ERROR_INVALID_PARAMETER)
            NoSuchProcess();
        else
            PyErr_SetFromWindowsErr(0);
        return NULL;
    }

    // make sure the process is running
    GetExitCodeProcess(hProcess, &processExitCode);
    if (processExitCode == 0) {
        NoSuchProcess();
        CloseHandle(hProcess);
        return NULL;
    }
    return hProcess;
}


/*
 * Same as psutil_handle_from_pid_waccess but implicitly uses
 * PROCESS_QUERY_INFORMATION | PROCESS_VM_READ as dwDesiredAccess
 * parameter for OpenProcess.
 */
HANDLE
psutil_handle_from_pid(DWORD pid) {
    DWORD dwDesiredAccess = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ;
    return psutil_handle_from_pid_waccess(pid, dwDesiredAccess);
}


/*
 * Given a Python int referencing a process handle close the process handle.
 */
PyObject *
psutil_win32_CloseHandle(PyObject *self, PyObject *args) {
    unsigned long handle;

    if (! PyArg_ParseTuple(args, "k", &handle))
        return NULL;
    // TODO: may want to check return value;
    CloseHandle((HANDLE)handle);
    Py_RETURN_NONE;
}


DWORD *
psutil_get_pids(DWORD *numberOfReturnedPIDs) {
    // Win32 SDK says the only way to know if our process array
    // wasn't large enough is to check the returned size and make
    // sure that it doesn't match the size of the array.
    // If it does we allocate a larger array and try again

    // Stores the actual array
    DWORD *procArray = NULL;
    DWORD procArrayByteSz;
    int procArraySz = 0;

    // Stores the byte size of the returned array from enumprocesses
    DWORD enumReturnSz = 0;

    do {
        procArraySz += 1024;
        free(procArray);
        procArrayByteSz = procArraySz * sizeof(DWORD);
        procArray = malloc(procArrayByteSz);
        if (procArray == NULL) {
            PyErr_NoMemory();
            return NULL;
        }
        if (! EnumProcesses(procArray, procArrayByteSz, &enumReturnSz)) {
            free(procArray);
            PyErr_SetFromWindowsErr(0);
            return NULL;
        }
    } while (enumReturnSz == procArraySz * sizeof(DWORD));

    // The number of elements is the returned size / size of each element
    *numberOfReturnedPIDs = enumReturnSz / sizeof(DWORD);

    return procArray;
}


int
psutil_pid_is_running(DWORD pid) {
    HANDLE hProcess;
    DWORD exitCode;

    // Special case for PID 0 System Idle Process
    if (pid == 0)
        return 1;
    if (pid < 0)
        return 0;

    hProcess = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                           FALSE, pid);
    if (NULL == hProcess) {
        // invalid parameter is no such process
        if (GetLastError() == ERROR_INVALID_PARAMETER) {
            CloseHandle(hProcess);
            return 0;
        }

        // access denied obviously means there's a process to deny access to...
        if (GetLastError() == ERROR_ACCESS_DENIED) {
            CloseHandle(hProcess);
            return 1;
        }

        CloseHandle(hProcess);
        PyErr_SetFromWindowsErr(0);
        return -1;
    }

    if (GetExitCodeProcess(hProcess, &exitCode)) {
        CloseHandle(hProcess);
        return (exitCode == STILL_ACTIVE);
    }

    // access denied means there's a process there so we'll assume
    // it's running
    if (GetLastError() == ERROR_ACCESS_DENIED) {
        CloseHandle(hProcess);
        return 1;
    }

    PyErr_SetFromWindowsErr(0);
    CloseHandle(hProcess);
    return -1;
}


int
psutil_pid_in_proclist(DWORD pid) {
    DWORD *proclist = NULL;
    DWORD numberOfReturnedPIDs;
    DWORD i;

    proclist = psutil_get_pids(&numberOfReturnedPIDs);
    if (proclist == NULL)
        return -1;
    for (i = 0; i < numberOfReturnedPIDs; i++) {
        if (pid == proclist[i]) {
            free(proclist);
            return 1;
        }
    }

    free(proclist);
    return 0;
}


// Check exit code from a process handle. Return FALSE on an error also
// XXX - not used anymore
int
handlep_is_running(HANDLE hProcess) {
    DWORD dwCode;

    if (NULL == hProcess)
        return 0;
    if (GetExitCodeProcess(hProcess, &dwCode)) {
        if (dwCode == STILL_ACTIVE)
            return 1;
    }
    return 0;
}

// Helper structures to access the memory correctly.  Some of these might also
// be defined in the winternl.h header file but unfortunately not in a usable
// way.

// see http://msdn2.microsoft.com/en-us/library/aa489609.aspx
#ifndef NT_SUCCESS
#define NT_SUCCESS(Status) ((NTSTATUS)(Status) >= 0)
#endif

// http://msdn.microsoft.com/en-us/library/aa813741(VS.85).aspx
typedef struct {
    BYTE Reserved1[16];
    PVOID Reserved2[5];
    UNICODE_STRING CurrentDirectoryPath;
    PVOID CurrentDirectoryHandle;
    UNICODE_STRING DllPath;
    UNICODE_STRING ImagePathName;
    UNICODE_STRING CommandLine;
    LPCWSTR env;
} RTL_USER_PROCESS_PARAMETERS_, *PRTL_USER_PROCESS_PARAMETERS_;

// https://msdn.microsoft.com/en-us/library/aa813706(v=vs.85).aspx
#ifdef _WIN64
typedef struct {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[21];
    PVOID LoaderData;
    PRTL_USER_PROCESS_PARAMETERS_ ProcessParameters;
    /* More fields ...  */
} PEB_;
#else
typedef struct {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[1];
    PVOID Reserved3[2];
    PVOID Ldr;
    PRTL_USER_PROCESS_PARAMETERS_ ProcessParameters;
    /* More fields ...  */
} PEB_;
#endif

#ifdef _WIN64
/* When we are a 64 bit process accessing a 32 bit (WoW64) process we need to
   use the 32 bit structure layout. */
typedef struct {
    USHORT Length;
    USHORT MaxLength;
    DWORD Buffer;
} UNICODE_STRING32;

typedef struct {
    BYTE Reserved1[16];
    DWORD Reserved2[5];
    UNICODE_STRING32 CurrentDirectoryPath;
    DWORD CurrentDirectoryHandle;
    UNICODE_STRING32 DllPath;
    UNICODE_STRING32 ImagePathName;
    UNICODE_STRING32 CommandLine;
    DWORD env;
} RTL_USER_PROCESS_PARAMETERS32;

typedef struct {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[1];
    DWORD Reserved3[2];
    DWORD Ldr;
    DWORD ProcessParameters;
    /* More fields ...  */
} PEB32;
#else
/* When we are a 32 bit (WoW64) process accessing a 64 bit process we need to
   use the 64 bit structure layout and a special function to read its memory.
   */
typedef NTSTATUS (NTAPI *_NtWow64ReadVirtualMemory64)(
        IN HANDLE ProcessHandle,
        IN PVOID64 BaseAddress,
        OUT PVOID Buffer,
        IN ULONG64 Size,
        OUT PULONG64 NumberOfBytesRead);

typedef enum {
    MemoryInformationBasic
} MEMORY_INFORMATION_CLASS;

typedef NTSTATUS (NTAPI *_NtWow64QueryVirtualMemory64)(
    IN HANDLE ProcessHandle,
    IN PVOID64 BaseAddress,
    IN MEMORY_INFORMATION_CLASS MemoryInformationClass,
    OUT PMEMORY_BASIC_INFORMATION64 MemoryInformation,
    IN ULONG64 Size,
    OUT PULONG64 ReturnLength OPTIONAL);

typedef struct {
    PVOID Reserved1[2];
    PVOID64 PebBaseAddress;
    PVOID Reserved2[4];
    PVOID UniqueProcessId[2];
    PVOID Reserved3[2];
} PROCESS_BASIC_INFORMATION64;

typedef struct {
    USHORT Length;
    USHORT MaxLength;
    PVOID64 Buffer;
} UNICODE_STRING64;

typedef struct {
    BYTE Reserved1[16];
    PVOID64 Reserved2[5];
    UNICODE_STRING64 CurrentDirectoryPath;
    PVOID64 CurrentDirectoryHandle;
    UNICODE_STRING64 DllPath;
    UNICODE_STRING64 ImagePathName;
    UNICODE_STRING64 CommandLine;
    PVOID64 env;
} RTL_USER_PROCESS_PARAMETERS64;

typedef struct {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[21];
    PVOID64 LoaderData;
    PVOID64 ProcessParameters;
    /* More fields ...  */
} PEB64;
#endif

/* Given a pointer into a process's memory, figure out how much data can be
 * read from it. */
static int psutil_get_process_region_size(HANDLE hProcess,
                                          LPCVOID src,
                                          SIZE_T *psize) {
    MEMORY_BASIC_INFORMATION info;

    if (!VirtualQueryEx(hProcess, src, &info, sizeof(info))) {
        PyErr_SetFromWindowsErr(0);
        return -1;
    }

    *psize = info.RegionSize - ((char*)src - (char*)info.BaseAddress);
    return 0;
}


#ifndef _WIN64
/* Given a pointer into a process's memory, figure out how much data can be
 * read from it. */
static int psutil_get_process_region_size64(HANDLE hProcess,
                                           const PVOID64 src64,
                                           PULONG64 psize) {
    static _NtWow64QueryVirtualMemory64 NtWow64QueryVirtualMemory64 = NULL;
    MEMORY_BASIC_INFORMATION64 info64;

    if (NtWow64QueryVirtualMemory64 == NULL) {
        NtWow64QueryVirtualMemory64 =
            (_NtWow64QueryVirtualMemory64)GetProcAddress(
                    GetModuleHandleA("ntdll.dll"),
                    "NtWow64QueryVirtualMemory64");

        if (NtWow64QueryVirtualMemory64 == NULL) {
            PyErr_SetString(PyExc_NotImplementedError,
                    "NtWow64QueryVirtualMemory64 missing");
            return -1;
        }
    }

    if (!NT_SUCCESS(NtWow64QueryVirtualMemory64(
                    hProcess,
                    src64,
                    0,
                    &info64,
                    sizeof(info64),
                    NULL))) {
        PyErr_SetFromWindowsErr(0);
        return -1;
    }

    *psize = info64.RegionSize - ((char*)src64 - (char*)info64.BaseAddress);
    return 0;
}
#endif


enum psutil_process_data_kind {
    KIND_CMDLINE,
    KIND_CWD,
    KIND_ENVIRON,
};

/* Get data from the process with the given pid.  The data is returned in the
   pdata output member as a nul terminated string which must be freed on
   success.

   On success 0 is returned.  On error the output parameter is not touched, -1
   is returned, and an appropriate Python exception is set. */
static int psutil_get_process_data(long pid,
                                   enum psutil_process_data_kind kind,
                                   WCHAR **pdata,
                                   SIZE_T *psize) {
    /* This function is quite complex because there are several cases to be
       considered:

       Two cases are really simple:  we (i.e. the python interpreter) and the
       target process are both 32 bit or both 64 bit.  In that case the memory
       layout of the structures matches up and all is well.

       When we are 64 bit and the target process is 32 bit we need to use
       custom 32 bit versions of the structures.

       When we are 32 bit and the target process is 64 bit we need to use
       custom 64 bit version of the structures.  Also we need to use separate
       Wow64 functions to get the information.

       A few helper structs are defined above so that the compiler can handle
       calculating the correct offsets.

       Additional help also came from the following sources:

         https://github.com/kohsuke/winp and
         http://wj32.org/wp/2009/01/24/howto-get-the-command-line-of-processes/
         http://stackoverflow.com/a/14012919
         http://www.drdobbs.com/embracing-64-bit-windows/184401966
     */
    static _NtQueryInformationProcess NtQueryInformationProcess = NULL;
#ifndef _WIN64
    static _NtQueryInformationProcess NtWow64QueryInformationProcess64 = NULL;
    static _NtWow64ReadVirtualMemory64 NtWow64ReadVirtualMemory64 = NULL;
#endif
    HANDLE hProcess = NULL;
    LPCVOID src;
    SIZE_T size;
    WCHAR *buffer = NULL;
#ifdef _WIN64
    LPVOID ppeb32 = NULL;
#else
    PVOID64 src64;
    BOOL weAreWow64;
    BOOL theyAreWow64;
#endif

    hProcess = psutil_handle_from_pid(pid);
    if (hProcess == NULL)
        return -1;

    if (NtQueryInformationProcess == NULL) {
        NtQueryInformationProcess = (_NtQueryInformationProcess)GetProcAddress(
                GetModuleHandleA("ntdll.dll"), "NtQueryInformationProcess");
    }

#ifdef _WIN64
    /* 64 bit case.  Check if the target is a 32 bit process running in WoW64
     * mode. */
    if (!NT_SUCCESS(NtQueryInformationProcess(hProcess,
                                              ProcessWow64Information,
                                              &ppeb32,
                                              sizeof(LPVOID),
                                              NULL))) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    if (ppeb32 != NULL) {
        /* We are 64 bit.  Target process is 32 bit running in WoW64 mode. */
        PEB32 peb32;
        RTL_USER_PROCESS_PARAMETERS32 procParameters32;

        // read PEB
        if (!ReadProcessMemory(hProcess, ppeb32, &peb32, sizeof(peb32), NULL)) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        // read process parameters
        if (!ReadProcessMemory(hProcess,
                              UlongToPtr(peb32.ProcessParameters),
                              &procParameters32,
                              sizeof(procParameters32),
                              NULL)) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        switch (kind) {
            case KIND_CMDLINE:
                src = UlongToPtr(procParameters32.CommandLine.Buffer),
                size = procParameters32.CommandLine.Length;
                break;
            case KIND_CWD:
                src = UlongToPtr(procParameters32.CurrentDirectoryPath.Buffer);
                size = procParameters32.CurrentDirectoryPath.Length;
                break;
            case KIND_ENVIRON:
                src = UlongToPtr(procParameters32.env);
                break;
        }
    } else
#else
    /* 32 bit case.  Check if the target is also 32 bit. */
    if (!IsWow64Process(GetCurrentProcess(), &weAreWow64) ||
        !IsWow64Process(hProcess, &theyAreWow64)) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    if (weAreWow64 && !theyAreWow64) {
        /* We are 32 bit running in WoW64 mode.  Target process is 64 bit. */
        PROCESS_BASIC_INFORMATION64 pbi64;
        PEB64 peb64;
        RTL_USER_PROCESS_PARAMETERS64 procParameters64;

        if (NtWow64QueryInformationProcess64 == NULL) {
            NtWow64QueryInformationProcess64 =
                (_NtQueryInformationProcess)GetProcAddress(
                        GetModuleHandleA("ntdll.dll"),
                        "NtWow64QueryInformationProcess64");

            if (NtWow64QueryInformationProcess64 == NULL) {
                PyErr_SetString(PyExc_NotImplementedError,
                                "NtWow64QueryInformationProcess64 missing");
                goto error;
            }
        }

        if (!NT_SUCCESS(NtWow64QueryInformationProcess64(
                        hProcess,
                        ProcessBasicInformation,
                        &pbi64,
                        sizeof(pbi64),
                        NULL))) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        // read peb
        if (NtWow64ReadVirtualMemory64 == NULL) {
            NtWow64ReadVirtualMemory64 =
                (_NtWow64ReadVirtualMemory64)GetProcAddress(
                        GetModuleHandleA("ntdll.dll"),
                        "NtWow64ReadVirtualMemory64");

            if (NtWow64ReadVirtualMemory64 == NULL) {
                PyErr_SetString(PyExc_NotImplementedError,
                                "NtWow64ReadVirtualMemory64 missing");
                goto error;
            }
        }

        if (!NT_SUCCESS(NtWow64ReadVirtualMemory64(hProcess,
                                                   pbi64.PebBaseAddress,
                                                   &peb64,
                                                   sizeof(peb64),
                                                   NULL))) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        // read process parameters
        if (!NT_SUCCESS(NtWow64ReadVirtualMemory64(hProcess,
                                                   peb64.ProcessParameters,
                                                   &procParameters64,
                                                   sizeof(procParameters64),
                                                   NULL))) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        switch (kind) {
            case KIND_CMDLINE:
                src64 = procParameters64.CommandLine.Buffer;
                size = procParameters64.CommandLine.Length;
                break;
            case KIND_CWD:
                src64 = procParameters64.CurrentDirectoryPath.Buffer,
                size = procParameters64.CurrentDirectoryPath.Length;
                break;
            case KIND_ENVIRON:
                src64 = procParameters64.env;
                break;
        }
    } else
#endif

    /* Target process is of the same bitness as us. */
    {
        PROCESS_BASIC_INFORMATION pbi;
        PEB_ peb;
        RTL_USER_PROCESS_PARAMETERS_ procParameters;

        if (!NT_SUCCESS(NtQueryInformationProcess(hProcess,
                                                  ProcessBasicInformation,
                                                  &pbi,
                                                  sizeof(pbi),
                                                  NULL))) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        // read peb
        if (!ReadProcessMemory(hProcess,
                               pbi.PebBaseAddress,
                               &peb,
                               sizeof(peb),
                               NULL)) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        // read process parameters
        if (!ReadProcessMemory(hProcess,
                               peb.ProcessParameters,
                               &procParameters,
                               sizeof(procParameters),
                               NULL)) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }

        switch (kind) {
            case KIND_CMDLINE:
                src = procParameters.CommandLine.Buffer;
                size = procParameters.CommandLine.Length;
                break;
            case KIND_CWD:
                src = procParameters.CurrentDirectoryPath.Buffer;
                size = procParameters.CurrentDirectoryPath.Length;
                break;
            case KIND_ENVIRON:
                src = procParameters.env;
                break;
        }
    }

    if (kind == KIND_ENVIRON) {
#ifndef _WIN64
        if (weAreWow64 && !theyAreWow64) {
            ULONG64 size64;

            if (psutil_get_process_region_size64(hProcess, src64, &size64) != 0)
                goto error;

            size = (SIZE_T)size64;
        }
        else
#endif
        if (psutil_get_process_region_size(hProcess, src, &size) != 0)
            goto error;
    }

    buffer = calloc(size + 2, 1);

    if (buffer == NULL) {
        PyErr_NoMemory();
        goto error;
    }

#ifndef _WIN64
    if (weAreWow64 && !theyAreWow64) {
        if (!NT_SUCCESS(NtWow64ReadVirtualMemory64(hProcess,
                                                   src64,
                                                   buffer,
                                                   size,
                                                   NULL))) {
            PyErr_SetFromWindowsErr(0);
            goto error;
        }
    } else
#endif
    if (!ReadProcessMemory(hProcess, src, buffer, size, NULL)) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    CloseHandle(hProcess);

    *pdata = buffer;
    *psize = size;

    return 0;

error:
    if (hProcess != NULL)
        CloseHandle(hProcess);
    if (buffer != NULL)
        free(buffer);
    return -1;
}

/*
 * returns a Python list representing the arguments for the process
 * with given pid or NULL on error.
 */
PyObject *
psutil_get_cmdline(long pid) {
    PyObject *ret = NULL;
    WCHAR *data = NULL;
    SIZE_T size;
    PyObject *py_retlist = NULL;
    PyObject *py_unicode = NULL;
    LPWSTR *szArglist = NULL;
    int nArgs, i;

    if (psutil_get_process_data(pid, KIND_CMDLINE, &data, &size) != 0)
        goto out;

    // attempt to parse the command line using Win32 API
    szArglist = CommandLineToArgvW(data, &nArgs);
    if (szArglist == NULL) {
        PyErr_SetFromWindowsErr(0);
        goto out;
    }

    // arglist parsed as array of UNICODE_STRING, so convert each to
    // Python string object and add to arg list
    py_retlist = PyList_New(nArgs);
    if (py_retlist == NULL)
        goto out;
    for (i = 0; i < nArgs; i++) {
        py_unicode = PyUnicode_FromWideChar(szArglist[i],
                                            wcslen(szArglist[i]));
        if (py_unicode == NULL)
            goto out;
        PyList_SET_ITEM(py_retlist, i, py_unicode);
        py_unicode = NULL;
    }

    ret = py_retlist;
    py_retlist = NULL;

out:
    LocalFree(szArglist);
    free(data);
    Py_XDECREF(py_unicode);
    Py_XDECREF(py_retlist);

    return ret;
}

PyObject *psutil_get_cwd(long pid) {
    PyObject *ret = NULL;
    WCHAR *data = NULL;
    SIZE_T size;

    if (psutil_get_process_data(pid, KIND_CWD, &data, &size) != 0)
        goto out;

    // convert wchar array to a Python unicode string
    ret = PyUnicode_FromWideChar(data, wcslen(data));

out:
    free(data);

    return ret;
}

/*
 * returns a Python string containing the environment variable data for the
 * process with given pid or NULL on error.
 */
PyObject *psutil_get_environ(long pid) {
    PyObject *ret = NULL;
    WCHAR *data = NULL;
    SIZE_T size;

    if (psutil_get_process_data(pid, KIND_ENVIRON, &data, &size) != 0)
        goto out;

    // convert wchar array to a Python unicode string
    ret = PyUnicode_FromWideChar(data, size / 2);

out:
    free(data);

    return ret;
}

#define PH_FIRST_PROCESS(Processes) ((PSYSTEM_PROCESS_INFORMATION)(Processes))
#define PH_NEXT_PROCESS(Process) ( \
   ((PSYSTEM_PROCESS_INFORMATION)(Process))->NextEntryOffset ? \
   (PSYSTEM_PROCESS_INFORMATION)((PCHAR)(Process) + \
        ((PSYSTEM_PROCESS_INFORMATION)(Process))->NextEntryOffset) : \
   NULL)

const int STATUS_INFO_LENGTH_MISMATCH = 0xC0000004;
const int STATUS_BUFFER_TOO_SMALL = 0xC0000023L;

/*
 * Given a process PID and a PSYSTEM_PROCESS_INFORMATION structure
 * fills the structure with various process information by using
 * NtQuerySystemInformation.
 * We use this as a fallback when faster functions fail with access
 * denied. This is slower because it iterates over all processes.
 * On success return 1, else 0 with Python exception already set.
 */
int
psutil_get_proc_info(DWORD pid, PSYSTEM_PROCESS_INFORMATION *retProcess,
                     PVOID *retBuffer) {
    static ULONG initialBufferSize = 0x4000;
    NTSTATUS status;
    PVOID buffer;
    ULONG bufferSize;
    PSYSTEM_PROCESS_INFORMATION process;

    // get NtQuerySystemInformation
    typedef DWORD (_stdcall * NTQSI_PROC) (int, PVOID, ULONG, PULONG);
    NTQSI_PROC NtQuerySystemInformation;
    HINSTANCE hNtDll;
    hNtDll = LoadLibrary(TEXT("ntdll.dll"));
    NtQuerySystemInformation = (NTQSI_PROC)GetProcAddress(
        hNtDll, "NtQuerySystemInformation");

    bufferSize = initialBufferSize;
    buffer = malloc(bufferSize);
    if (buffer == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    while (TRUE) {
        status = NtQuerySystemInformation(SystemProcessInformation, buffer,
                                          bufferSize, &bufferSize);

        if (status == STATUS_BUFFER_TOO_SMALL ||
                status == STATUS_INFO_LENGTH_MISMATCH)
        {
            free(buffer);
            buffer = malloc(bufferSize);
            if (buffer == NULL) {
                PyErr_NoMemory();
                goto error;
            }
        }
        else {
            break;
        }
    }

    if (status != 0) {
        PyErr_Format(
            PyExc_RuntimeError, "NtQuerySystemInformation() syscall failed");
        goto error;
    }

    if (bufferSize <= 0x20000)
        initialBufferSize = bufferSize;

    process = PH_FIRST_PROCESS(buffer);
    do {
        if (process->UniqueProcessId == (HANDLE)pid) {
            *retProcess = process;
            *retBuffer = buffer;
            return 1;
        }
    } while ( (process = PH_NEXT_PROCESS(process)) );

    NoSuchProcess();
    goto error;

error:
    FreeLibrary(hNtDll);
    if (buffer != NULL)
        free(buffer);
    return 0;
}
