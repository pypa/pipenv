/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include <Python.h>
#include <windows.h>
#include <Winsvc.h>

#include "services.h"


// ==================================================================
// utils
// ==================================================================

SC_HANDLE
psutil_get_service_handler(char *service_name, DWORD scm_access, DWORD access)
{
    ENUM_SERVICE_STATUS_PROCESS *lpService = NULL;
    SC_HANDLE sc = NULL;
    SC_HANDLE hService = NULL;
    SERVICE_DESCRIPTION *scd = NULL;

    sc = OpenSCManager(NULL, NULL, scm_access);
    if (sc == NULL) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    hService = OpenService(sc, service_name, access);
    if (hService == NULL) {
        CloseServiceHandle(sc);
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }
    CloseServiceHandle(sc);
    return hService;
}


// XXX - expose these as constants?
static const char *
get_startup_string(DWORD startup) {
    switch (startup) {
        case SERVICE_AUTO_START:
            return "automatic";
        case SERVICE_DEMAND_START:
            return "manual";
        case SERVICE_DISABLED:
            return "disabled";
/*
        // drivers only (since we use EnumServicesStatusEx() with
        // SERVICE_WIN32)
        case SERVICE_BOOT_START:
            return "boot-start";
        case SERVICE_SYSTEM_START:
            return "system-start";
*/
        default:
            return "unknown";
    }
}


// XXX - expose these as constants?
static const char *
get_state_string(DWORD state) {
    switch (state) {
        case SERVICE_RUNNING:
            return "running";
        case SERVICE_PAUSED:
            return "paused";
        case SERVICE_START_PENDING:
            return "start_pending";
        case SERVICE_PAUSE_PENDING:
            return "pause_pending";
        case SERVICE_CONTINUE_PENDING:
            return "continue_pending";
        case SERVICE_STOP_PENDING:
            return "stop_pending";
        case SERVICE_STOPPED:
            return "stopped";
        default:
            return "unknown";
    }
}


// ==================================================================
// APIs
// ==================================================================

/*
 * Enumerate all services.
 */
PyObject *
psutil_winservice_enumerate(PyObject *self, PyObject *args) {
    ENUM_SERVICE_STATUS_PROCESS *lpService = NULL;
    BOOL ok;
    SC_HANDLE sc = NULL;
    DWORD bytesNeeded = 0;
    DWORD srvCount;
    DWORD resumeHandle = 0;
    DWORD dwBytes = 0;
    DWORD i;
    PyObject *py_retlist = PyList_New(0);
    PyObject *py_tuple = NULL;
    PyObject *py_unicode_display_name = NULL;

    if (py_retlist == NULL)
        return NULL;

    sc = OpenSCManager(NULL, NULL, SC_MANAGER_ENUMERATE_SERVICE);
    if (sc == NULL) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }

    for (;;) {
        ok = EnumServicesStatusEx(
            sc,
            SC_ENUM_PROCESS_INFO,
            SERVICE_WIN32,  // XXX - extend this to include drivers etc.?
            SERVICE_STATE_ALL,
            (LPBYTE)lpService,
            dwBytes,
            &bytesNeeded,
            &srvCount,
            &resumeHandle,
            NULL);
        if (ok || (GetLastError() != ERROR_MORE_DATA))
            break;
        if (lpService)
            free(lpService);
        dwBytes = bytesNeeded;
        lpService = (ENUM_SERVICE_STATUS_PROCESS*)malloc(dwBytes);
    }

    for (i = 0; i < srvCount; i++) {
        // Get unicode display name.
        py_unicode_display_name = NULL;
        py_unicode_display_name = PyUnicode_Decode(
            lpService[i].lpDisplayName,
            _tcslen(lpService[i].lpDisplayName),
            Py_FileSystemDefaultEncoding,
            "replace");
        if (py_unicode_display_name == NULL)
            goto error;

        // Construct the result.
        py_tuple = Py_BuildValue(
            "(sO)",
            lpService[i].lpServiceName,  // name
            py_unicode_display_name  // display_name
        );
        if (py_tuple == NULL)
            goto error;
        if (PyList_Append(py_retlist, py_tuple))
            goto error;
        Py_DECREF(py_unicode_display_name);
        Py_DECREF(py_tuple);
    }

    // Free resources.
    CloseServiceHandle(sc);
    free(lpService);
    return py_retlist;

error:
    Py_XDECREF(py_unicode_display_name);
    Py_XDECREF(py_tuple);
    Py_DECREF(py_retlist);
    if (sc != NULL)
        CloseServiceHandle(sc);
    if (lpService != NULL)
        free(lpService);
    return NULL;
}


/*
 * Get service config information. Returns:
 * - display_name
 * - binpath
 * - username
 * - startup_type
 */
PyObject *
psutil_winservice_query_config(PyObject *self, PyObject *args) {
    char *service_name;
    SC_HANDLE hService = NULL;
    BOOL ok;
    DWORD bytesNeeded = 0;
    DWORD resumeHandle = 0;
    DWORD dwBytes = 0;
    QUERY_SERVICE_CONFIG *qsc = NULL;
    PyObject *py_tuple = NULL;
    PyObject *py_unicode_display_name = NULL;
    PyObject *py_unicode_binpath = NULL;
    PyObject *py_unicode_username = NULL;

    if (!PyArg_ParseTuple(args, "s", &service_name))
        return NULL;
    hService = psutil_get_service_handler(
        service_name, SC_MANAGER_ENUMERATE_SERVICE, SERVICE_QUERY_CONFIG);
    if (hService == NULL)
        goto error;

    // First call to QueryServiceConfig() is necessary to get the
    // right size.
    bytesNeeded = 0;
    QueryServiceConfig(hService, NULL, 0, &bytesNeeded);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }
    qsc = (QUERY_SERVICE_CONFIG *)malloc(bytesNeeded);
    ok = QueryServiceConfig(hService, qsc, bytesNeeded, &bytesNeeded);
    if (ok == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    // Get unicode display name.
    py_unicode_display_name = PyUnicode_Decode(
        qsc->lpDisplayName,
        _tcslen(qsc->lpDisplayName),
        Py_FileSystemDefaultEncoding,
        "replace");
    if (py_unicode_display_name == NULL)
        goto error;

    // Get unicode bin path.
    py_unicode_binpath = PyUnicode_Decode(
        qsc->lpBinaryPathName,
        _tcslen(qsc->lpBinaryPathName),
        Py_FileSystemDefaultEncoding,
        "replace");
    if (py_unicode_binpath == NULL)
        goto error;

    // Get unicode username.
    py_unicode_username = PyUnicode_Decode(
        qsc->lpServiceStartName,
        _tcslen(qsc->lpServiceStartName),
        Py_FileSystemDefaultEncoding,
        "replace");
    if (py_unicode_username == NULL)
        goto error;

    // Construct result tuple.
    py_tuple = Py_BuildValue(
        "(OOOs)",
        py_unicode_display_name,
        py_unicode_binpath,
        py_unicode_username,
        get_startup_string(qsc->dwStartType)  // startup
    );
    if (py_tuple == NULL)
        goto error;

    // Free resources.
    Py_DECREF(py_unicode_display_name);
    Py_DECREF(py_unicode_binpath);
    Py_DECREF(py_unicode_username);
    free(qsc);
    CloseServiceHandle(hService);
    return py_tuple;

error:
    Py_XDECREF(py_unicode_display_name);
    Py_XDECREF(py_unicode_binpath);
    Py_XDECREF(py_unicode_username);
    Py_XDECREF(py_tuple);
    if (hService != NULL)
        CloseServiceHandle(hService);
    if (qsc != NULL)
        free(qsc);
    return NULL;
}


/*
 * Get service status information. Returns:
 * - status
 * - pid
 */
PyObject *
psutil_winservice_query_status(PyObject *self, PyObject *args) {
    char *service_name;
    SC_HANDLE hService = NULL;
    BOOL ok;
    DWORD bytesNeeded = 0;
    DWORD resumeHandle = 0;
    DWORD dwBytes = 0;
    SERVICE_STATUS_PROCESS  *ssp = NULL;
    PyObject *py_tuple = NULL;

    if (!PyArg_ParseTuple(args, "s", &service_name))
        return NULL;
    hService = psutil_get_service_handler(
        service_name, SC_MANAGER_ENUMERATE_SERVICE, SERVICE_QUERY_STATUS);
    if (hService == NULL)
        goto error;

    // First call to QueryServiceStatusEx() is necessary to get the
    // right size.
    QueryServiceStatusEx(hService, SC_STATUS_PROCESS_INFO, NULL, 0,
                         &bytesNeeded);
    if (GetLastError() == ERROR_MUI_FILE_NOT_FOUND) {
        // Also services.msc fails in the same manner, so we return an
        // empty string.
        CloseServiceHandle(hService);
        return Py_BuildValue("s", "");
    }
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }
    ssp = (SERVICE_STATUS_PROCESS *)HeapAlloc(
        GetProcessHeap(), 0, bytesNeeded);
    if (ssp == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    // Actual call.
    ok = QueryServiceStatusEx(hService, SC_STATUS_PROCESS_INFO, (LPBYTE)ssp,
                              bytesNeeded, &bytesNeeded);
    if (ok == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    py_tuple = Py_BuildValue(
        "(sk)",
        get_state_string(ssp->dwCurrentState),
        ssp->dwProcessId
    );
    if (py_tuple == NULL)
        goto error;

    CloseServiceHandle(hService);
    HeapFree(GetProcessHeap(), 0, ssp);
    return py_tuple;

error:
    Py_XDECREF(py_tuple);
    if (hService != NULL)
        CloseServiceHandle(hService);
    if (ssp != NULL)
        HeapFree(GetProcessHeap(), 0, ssp);
    return NULL;
}


/*
 * Get service description.
 */
PyObject *
psutil_winservice_query_descr(PyObject *self, PyObject *args) {
    ENUM_SERVICE_STATUS_PROCESS *lpService = NULL;
    BOOL ok;
    DWORD bytesNeeded = 0;
    DWORD resumeHandle = 0;
    DWORD dwBytes = 0;
    SC_HANDLE hService = NULL;
    SERVICE_DESCRIPTION *scd = NULL;
    char *service_name;
    PyObject *py_retstr = NULL;

    if (!PyArg_ParseTuple(args, "s", &service_name))
        return NULL;
    hService = psutil_get_service_handler(
        service_name, SC_MANAGER_ENUMERATE_SERVICE, SERVICE_QUERY_CONFIG);
    if (hService == NULL)
        goto error;

    // This first call to QueryServiceConfig2() is necessary in order
    // to get the right size.
    bytesNeeded = 0;
    QueryServiceConfig2(hService, SERVICE_CONFIG_DESCRIPTION, NULL, 0,
                        &bytesNeeded);
    if (GetLastError() == ERROR_MUI_FILE_NOT_FOUND) {
        // Also services.msc fails in the same manner, so we return an
        // empty string.
        CloseServiceHandle(hService);
        return Py_BuildValue("s", "");
    }
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    scd = (SERVICE_DESCRIPTION *)malloc(bytesNeeded);
    ok = QueryServiceConfig2(hService, SERVICE_CONFIG_DESCRIPTION,
                             (LPBYTE)scd, bytesNeeded, &bytesNeeded);
    if (ok == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    if (scd->lpDescription == NULL) {
        py_retstr = Py_BuildValue("s", "");
    }
    else {
        py_retstr = PyUnicode_Decode(
            scd->lpDescription,
            _tcslen(scd->lpDescription),
            Py_FileSystemDefaultEncoding,
            "replace");
    }
    if (!py_retstr)
        goto error;

    free(scd);
    CloseServiceHandle(hService);
    return py_retstr;

error:
    if (hService != NULL)
        CloseServiceHandle(hService);
    if (lpService != NULL)
        free(lpService);
    return NULL;
}


/*
 * Start service.
 * XXX - note: this is exposed but not used.
 */
PyObject *
psutil_winservice_start(PyObject *self, PyObject *args) {
    char *service_name;
    BOOL ok;
    SC_HANDLE hService = NULL;

    if (!PyArg_ParseTuple(args, "s", &service_name))
        return NULL;
    hService = psutil_get_service_handler(
        service_name, SC_MANAGER_ALL_ACCESS, SERVICE_START);
    if (hService == NULL) {
        goto error;
    }
    ok = StartService(hService, 0, NULL);
    if (ok == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    Py_RETURN_NONE;

error:
    if (hService != NULL)
        CloseServiceHandle(hService);
    return NULL;
}


/*
 * Stop service.
 * XXX - note: this is exposed but not used.
 */
PyObject *
psutil_winservice_stop(PyObject *self, PyObject *args) {
    char *service_name;
    BOOL ok;
    SC_HANDLE hService = NULL;
    SERVICE_STATUS ssp;

    if (!PyArg_ParseTuple(args, "s", &service_name))
        return NULL;
    hService = psutil_get_service_handler(
        service_name, SC_MANAGER_ALL_ACCESS, SERVICE_STOP);
    if (hService == NULL)
        goto error;

    // Note: this can hang for 30 secs.
    Py_BEGIN_ALLOW_THREADS
    ok = ControlService(hService, SERVICE_CONTROL_STOP, &ssp);
    Py_END_ALLOW_THREADS
    if (ok == 0) {
        PyErr_SetFromWindowsErr(0);
        goto error;
    }

    CloseServiceHandle(hService);
    Py_RETURN_NONE;

error:
    if (hService != NULL)
        CloseServiceHandle(hService);
    return NULL;
}
