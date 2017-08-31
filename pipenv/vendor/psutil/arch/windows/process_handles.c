/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 */
#include "process_handles.h"

static _NtQuerySystemInformation __NtQuerySystemInformation = NULL;
static _NtQueryObject __NtQueryObject = NULL;

CRITICAL_SECTION g_cs;
BOOL g_initialized = FALSE;
NTSTATUS g_status;
HANDLE g_hFile = NULL;
HANDLE g_hEvtStart = NULL;
HANDLE g_hEvtFinish = NULL;
HANDLE g_hThread = NULL;
PUNICODE_STRING g_pNameBuffer = NULL;
ULONG g_dwSize = 0;
ULONG g_dwLength = 0;


PVOID
GetLibraryProcAddress(PSTR LibraryName, PSTR ProcName) {
    return GetProcAddress(GetModuleHandleA(LibraryName), ProcName);
}


PyObject *
psutil_get_open_files(long dwPid, HANDLE hProcess) {
    OSVERSIONINFO osvi;

    ZeroMemory(&osvi, sizeof(OSVERSIONINFO));
    osvi.dwOSVersionInfoSize = sizeof(OSVERSIONINFO);
    GetVersionEx(&osvi);

    // Threaded version only works for Vista+
    if (osvi.dwMajorVersion >= 6)
        return psutil_get_open_files_ntqueryobject(dwPid, hProcess);
    else
        return psutil_get_open_files_getmappedfilename(dwPid, hProcess);
}


VOID
psutil_get_open_files_init(BOOL threaded) {
    if (g_initialized == TRUE)
        return;

    // Resolve the Windows API calls
    __NtQuerySystemInformation =
        GetLibraryProcAddress("ntdll.dll", "NtQuerySystemInformation");
    __NtQueryObject = GetLibraryProcAddress("ntdll.dll", "NtQueryObject");

    // Create events for signalling work between threads
    if (threaded == TRUE) {
        g_hEvtStart = CreateEvent(NULL, FALSE, FALSE, NULL);
        g_hEvtFinish = CreateEvent(NULL, FALSE, FALSE, NULL);
        InitializeCriticalSection(&g_cs);
    }

    g_initialized = TRUE;
}


PyObject *
psutil_get_open_files_ntqueryobject(long dwPid, HANDLE hProcess) {
    NTSTATUS                            status;
    PSYSTEM_HANDLE_INFORMATION_EX       pHandleInfo = NULL;
    DWORD                               dwInfoSize = 0x10000;
    DWORD                               dwRet = 0;
    PSYSTEM_HANDLE_TABLE_ENTRY_INFO_EX  hHandle = NULL;
    DWORD                               i = 0;
    BOOLEAN                             error = FALSE;
    DWORD                               dwWait = 0;
    PyObject*                           py_retlist = NULL;
    PyObject*                           py_path = NULL;

    if (g_initialized == FALSE)
        psutil_get_open_files_init(TRUE);

    // Due to the use of global variables, ensure only 1 call
    // to psutil_get_open_files() is running
    EnterCriticalSection(&g_cs);

    if (__NtQuerySystemInformation == NULL ||
        __NtQueryObject == NULL ||
        g_hEvtStart == NULL ||
        g_hEvtFinish == NULL)

    {
        PyErr_SetFromWindowsErr(0);
        error = TRUE;
        goto cleanup;
    }

    // Py_BuildValue raises an exception if NULL is returned
    py_retlist = PyList_New(0);
    if (py_retlist == NULL) {
        error = TRUE;
        goto cleanup;
    }

    do {
        if (pHandleInfo != NULL) {
            HeapFree(GetProcessHeap(), 0, pHandleInfo);
            pHandleInfo = NULL;
        }

        // NtQuerySystemInformation won't give us the correct buffer size,
        // so we guess by doubling the buffer size.
        dwInfoSize *= 2;
        pHandleInfo = HeapAlloc(GetProcessHeap(),
                                HEAP_ZERO_MEMORY,
                                dwInfoSize);

        if (pHandleInfo == NULL) {
            PyErr_NoMemory();
            error = TRUE;
            goto cleanup;
        }
    } while ((status = __NtQuerySystemInformation(
                            SystemExtendedHandleInformation,
                            pHandleInfo,
                            dwInfoSize,
                            &dwRet)) == STATUS_INFO_LENGTH_MISMATCH);

    // NtQuerySystemInformation stopped giving us STATUS_INFO_LENGTH_MISMATCH
    if (!NT_SUCCESS(status)) {
        PyErr_SetFromWindowsErr(HRESULT_FROM_NT(status));
        error = TRUE;
        goto cleanup;
    }

    for (i = 0; i < pHandleInfo->NumberOfHandles; i++) {
        hHandle = &pHandleInfo->Handles[i];

        // Check if this hHandle belongs to the PID the user specified.
        if (hHandle->UniqueProcessId != (HANDLE)dwPid)
            goto loop_cleanup;

        if (!DuplicateHandle(hProcess,
                             hHandle->HandleValue,
                             GetCurrentProcess(),
                             &g_hFile,
                             0,
                             TRUE,
                             DUPLICATE_SAME_ACCESS))
        {
            /*
            printf("[%d] DuplicateHandle (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            goto loop_cleanup;
        }

        // Guess buffer size is MAX_PATH + 1
        g_dwLength = (MAX_PATH+1) * sizeof(WCHAR);

        do {
            // Release any previously allocated buffer
            if (g_pNameBuffer != NULL) {
                HeapFree(GetProcessHeap(), 0, g_pNameBuffer);
                g_pNameBuffer = NULL;
                g_dwSize = 0;
            }

            // NtQueryObject puts the required buffer size in g_dwLength
            // WinXP edge case puts g_dwLength == 0, just skip this handle
            if (g_dwLength == 0)
                goto loop_cleanup;

            g_dwSize = g_dwLength;
            if (g_dwSize > 0) {
                g_pNameBuffer = HeapAlloc(GetProcessHeap(),
                                          HEAP_ZERO_MEMORY,
                                          g_dwSize);

                if (g_pNameBuffer == NULL)
                    goto loop_cleanup;
            }

            dwWait = psutil_NtQueryObject();

            // If the call does not return, skip this handle
            if (dwWait != WAIT_OBJECT_0)
                goto loop_cleanup;

        } while (g_status == STATUS_INFO_LENGTH_MISMATCH);

        // NtQueryObject stopped returning STATUS_INFO_LENGTH_MISMATCH
        if (!NT_SUCCESS(g_status))
            goto loop_cleanup;

        // Convert to PyUnicode and append it to the return list
        if (g_pNameBuffer->Length > 0) {
            /*
            printf("[%d] Filename (%#x) %#d bytes: %S\n",
                   dwPid,
                   hHandle->HandleValue,
                   g_pNameBuffer->Length,
                   g_pNameBuffer->Buffer);
            */

            py_path = PyUnicode_FromWideChar(g_pNameBuffer->Buffer,
                                                g_pNameBuffer->Length/2);
            if (py_path == NULL) {
                /*
                printf("[%d] PyUnicode_FromWideChar (%#x): %#x \n",
                       dwPid,
                       hHandle->HandleValue,
                       GetLastError());
                */
                error = TRUE;
                goto loop_cleanup;
            }

            if (PyList_Append(py_retlist, py_path)) {
                /*
                printf("[%d] PyList_Append (%#x): %#x \n",
                       dwPid,
                       hHandle->HandleValue,
                       GetLastError());
                */
                error = TRUE;
                goto loop_cleanup;
            }
        }

loop_cleanup:
        Py_XDECREF(py_path);
        py_path = NULL;

        if (g_pNameBuffer != NULL)
            HeapFree(GetProcessHeap(), 0, g_pNameBuffer);
        g_pNameBuffer = NULL;
        g_dwSize = 0;
        g_dwLength = 0;

        if (g_hFile != NULL)
            CloseHandle(g_hFile);
        g_hFile = NULL;
    }

cleanup:
    if (g_pNameBuffer != NULL)
        HeapFree(GetProcessHeap(), 0, g_pNameBuffer);
    g_pNameBuffer = NULL;
    g_dwSize = 0;
    g_dwLength = 0;

    if (g_hFile != NULL)
        CloseHandle(g_hFile);
    g_hFile = NULL;

    if (pHandleInfo != NULL)
        HeapFree(GetProcessHeap(), 0, pHandleInfo);
    pHandleInfo = NULL;

    if (error) {
        Py_XDECREF(py_retlist);
        py_retlist = NULL;
    }

    LeaveCriticalSection(&g_cs);

    return py_retlist;
}


DWORD
psutil_NtQueryObject() {
    DWORD dwWait = 0;

    if (g_hThread == NULL)
        g_hThread = CreateThread(
            NULL,
            0,
            psutil_NtQueryObjectThread,
            NULL,
            0,
            NULL);
    if (g_hThread == NULL)
        return GetLastError();

    // Signal the worker thread to start
    SetEvent(g_hEvtStart);

    // Wait for the worker thread to finish
    dwWait = WaitForSingleObject(g_hEvtFinish, NTQO_TIMEOUT);

    // If the thread hangs, kill it and cleanup
    if (dwWait == WAIT_TIMEOUT) {
        SuspendThread(g_hThread);
        TerminateThread(g_hThread, 1);
        WaitForSingleObject(g_hThread, INFINITE);
        CloseHandle(g_hThread);

        g_hThread = NULL;
    }

    return dwWait;
}


DWORD WINAPI
psutil_NtQueryObjectThread(LPVOID lpvParam) {
    // Loop infinitely waiting for work
    while (TRUE) {
        WaitForSingleObject(g_hEvtStart, INFINITE);

        g_status = __NtQueryObject(g_hFile,
                                   ObjectNameInformation,
                                   g_pNameBuffer,
                                   g_dwSize,
                                   &g_dwLength);
        SetEvent(g_hEvtFinish);
    }
}


PyObject *
psutil_get_open_files_getmappedfilename(long dwPid, HANDLE hProcess) {
    NTSTATUS                            status;
    PSYSTEM_HANDLE_INFORMATION_EX       pHandleInfo = NULL;
    DWORD                               dwInfoSize = 0x10000;
    DWORD                               dwRet = 0;
    PSYSTEM_HANDLE_TABLE_ENTRY_INFO_EX  hHandle = NULL;
    HANDLE                              hFile = NULL;
    HANDLE                              hMap = NULL;
    DWORD                               i = 0;
    BOOLEAN                             error = FALSE;
    PyObject*                           py_retlist = NULL;
    PyObject*                           py_path = NULL;
    ULONG                               dwSize = 0;
    LPVOID                              pMem = NULL;
    TCHAR                               pszFilename[MAX_PATH+1];

    if (g_initialized == FALSE)
        psutil_get_open_files_init(FALSE);

    if (__NtQuerySystemInformation == NULL || __NtQueryObject == NULL) {
        PyErr_SetFromWindowsErr(0);
        error = TRUE;
        goto cleanup;
    }

    // Py_BuildValue raises an exception if NULL is returned
    py_retlist = PyList_New(0);
    if (py_retlist == NULL) {
        error = TRUE;
        goto cleanup;
    }

    do {
        if (pHandleInfo != NULL) {
            HeapFree(GetProcessHeap(), 0, pHandleInfo);
            pHandleInfo = NULL;
        }

        // NtQuerySystemInformation won't give us the correct buffer size,
        // so we guess by doubling the buffer size.
        dwInfoSize *= 2;
        pHandleInfo = HeapAlloc(GetProcessHeap(),
                                HEAP_ZERO_MEMORY,
                                dwInfoSize);

        if (pHandleInfo == NULL) {
            PyErr_NoMemory();
            error = TRUE;
            goto cleanup;
        }
    } while ((status = __NtQuerySystemInformation(
                            SystemExtendedHandleInformation,
                            pHandleInfo,
                            dwInfoSize,
                            &dwRet)) == STATUS_INFO_LENGTH_MISMATCH);

    // NtQuerySystemInformation stopped giving us STATUS_INFO_LENGTH_MISMATCH
    if (!NT_SUCCESS(status)) {
        PyErr_SetFromWindowsErr(HRESULT_FROM_NT(status));
        error = TRUE;
        goto cleanup;
    }

    for (i = 0; i < pHandleInfo->NumberOfHandles; i++) {
        hHandle = &pHandleInfo->Handles[i];

        // Check if this hHandle belongs to the PID the user specified.
        if (hHandle->UniqueProcessId != (HANDLE)dwPid)
            goto loop_cleanup;

        if (!DuplicateHandle(hProcess,
                             hHandle->HandleValue,
                             GetCurrentProcess(),
                             &hFile,
                             0,
                             TRUE,
                             DUPLICATE_SAME_ACCESS))
        {
            /*
            printf("[%d] DuplicateHandle (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            goto loop_cleanup;
        }

        hMap = CreateFileMapping(hFile, NULL, PAGE_READONLY, 0, 0, NULL);
        if (hMap == NULL) {
            /*
            printf("[%d] CreateFileMapping (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            goto loop_cleanup;
        }

        pMem = MapViewOfFile(hMap, FILE_MAP_READ, 0, 0, 1);

        if (pMem == NULL) {
            /*
            printf("[%d] MapViewOfFile (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            goto loop_cleanup;
        }

        dwSize = GetMappedFileName(
            GetCurrentProcess(), pMem, pszFilename, MAX_PATH);
        if (dwSize == 0) {
            /*
            printf("[%d] GetMappedFileName (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            goto loop_cleanup;
        }

        pszFilename[dwSize] = '\0';
        /*
        printf("[%d] Filename (%#x) %#d bytes: %S\n",
               dwPid,
               hHandle->HandleValue,
               dwSize,
               pszFilename);
        */

        py_path = PyUnicode_FromWideChar(pszFilename, dwSize);
        if (py_path == NULL) {
            /*
            printf("[%d] PyUnicode_FromStringAndSize (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            error = TRUE;
            goto loop_cleanup;
        }

        if (PyList_Append(py_retlist, py_path)) {
            /*
            printf("[%d] PyList_Append (%#x): %#x \n",
                   dwPid,
                   hHandle->HandleValue,
                   GetLastError());
            */
            error = TRUE;
            goto loop_cleanup;
        }

loop_cleanup:
        Py_XDECREF(py_path);
        py_path = NULL;

        if (pMem != NULL)
            UnmapViewOfFile(pMem);
        pMem = NULL;

        if (hMap != NULL)
            CloseHandle(hMap);
        hMap = NULL;

        if (hFile != NULL)
            CloseHandle(hFile);
        hFile = NULL;

        dwSize = 0;
    }

cleanup:
    if (pMem != NULL)
        UnmapViewOfFile(pMem);
    pMem = NULL;

    if (hMap != NULL)
        CloseHandle(hMap);
    hMap = NULL;

    if (hFile != NULL)
        CloseHandle(hFile);
    hFile = NULL;

    if (pHandleInfo != NULL)
        HeapFree(GetProcessHeap(), 0, pHandleInfo);
    pHandleInfo = NULL;

    if (error) {
        Py_XDECREF(py_retlist);
        py_retlist = NULL;
    }

    return py_retlist;
}
