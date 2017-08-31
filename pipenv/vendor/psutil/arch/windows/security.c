/*
 * Copyright (c) 2009, Jay Loden, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Security related functions for Windows platform (Set privileges such as
 * SeDebug), as well as security helper functions.
 */

#include <windows.h>
#include <Python.h>


/*
 * Convert a process handle to a process token handle.
 */
HANDLE
psutil_token_from_handle(HANDLE hProcess) {
    HANDLE hToken = NULL;

    if (! OpenProcessToken(hProcess, TOKEN_QUERY, &hToken))
        return PyErr_SetFromWindowsErr(0);
    return hToken;
}


/*
 * http://www.ddj.com/windows/184405986
 *
 * There's a way to determine whether we're running under the Local System
 * account. However (you guessed it), we have to call more Win32 functions to
 * determine this. Backing up through the code listing, we need to make another
 * call to GetTokenInformation, but instead of passing through the TOKEN_USER
 * constant, we pass through the TOKEN_PRIVILEGES constant. This value returns
 * an array of privileges that the account has in the environment. Iterating
 * through the array, we call the function LookupPrivilegeName looking for the
 * string “SeTcbPrivilege. If the function returns this string, then this
 * account has Local System privileges
 */
int
psutil_has_system_privilege(HANDLE hProcess) {
    DWORD i;
    DWORD dwSize = 0;
    DWORD dwRetval = 0;
    TCHAR privName[256];
    DWORD dwNameSize = 256;
    // PTOKEN_PRIVILEGES tp = NULL;
    BYTE *pBuffer = NULL;
    TOKEN_PRIVILEGES *tp = NULL;
    HANDLE hToken = psutil_token_from_handle(hProcess);

    if (NULL == hToken)
        return -1;
    // call GetTokenInformation first to get the buffer size
    if (! GetTokenInformation(hToken, TokenPrivileges, NULL, 0, &dwSize)) {
        dwRetval = GetLastError();
        // if it failed for a reason other than the buffer, bail out
        if (dwRetval != ERROR_INSUFFICIENT_BUFFER ) {
            PyErr_SetFromWindowsErr(dwRetval);
            return 0;
        }
    }

    // allocate buffer and call GetTokenInformation again
    // tp = (PTOKEN_PRIVILEGES) GlobalAlloc(GPTR, dwSize);
    pBuffer = (BYTE *) malloc(dwSize);
    if (pBuffer == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    if (! GetTokenInformation(hToken, TokenPrivileges, pBuffer,
                              dwSize, &dwSize))
    {
        PyErr_SetFromWindowsErr(0);
        free(pBuffer);
        return -1;
    }

    // convert the BYTE buffer to a TOKEN_PRIVILEGES struct pointer
    tp = (TOKEN_PRIVILEGES *)pBuffer;

    // check all the privileges looking for SeTcbPrivilege
    for (i = 0; i < tp->PrivilegeCount; i++) {
        // reset the buffer contents and the buffer size
        strcpy(privName, "");
        dwNameSize = sizeof(privName) / sizeof(TCHAR);
        if (! LookupPrivilegeName(NULL,
                                  &tp->Privileges[i].Luid,
                                  (LPTSTR)privName,
                                  &dwNameSize))
        {
            PyErr_SetFromWindowsErr(0);
            free(pBuffer);
            return -1;
        }

        // if we find the SeTcbPrivilege then it's a LocalSystem process
        if (! lstrcmpi(privName, TEXT("SeTcbPrivilege"))) {
            free(pBuffer);
            return 1;
        }
    }

    free(pBuffer);
    return 0;
}


BOOL
psutil_set_privilege(HANDLE hToken, LPCTSTR Privilege, BOOL bEnablePrivilege) {
    TOKEN_PRIVILEGES tp;
    LUID luid;
    TOKEN_PRIVILEGES tpPrevious;
    DWORD cbPrevious = sizeof(TOKEN_PRIVILEGES);

    if (!LookupPrivilegeValue( NULL, Privilege, &luid )) return FALSE;

    // first pass.  get current privilege setting
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = 0;

    AdjustTokenPrivileges(
        hToken,
        FALSE,
        &tp,
        sizeof(TOKEN_PRIVILEGES),
        &tpPrevious,
        &cbPrevious
    );

    if (GetLastError() != ERROR_SUCCESS) return FALSE;

    // second pass. set privilege based on previous setting
    tpPrevious.PrivilegeCount = 1;
    tpPrevious.Privileges[0].Luid = luid;

    if (bEnablePrivilege)
        tpPrevious.Privileges[0].Attributes |= (SE_PRIVILEGE_ENABLED);
    else
        tpPrevious.Privileges[0].Attributes ^=
            (SE_PRIVILEGE_ENABLED & tpPrevious.Privileges[0].Attributes);

    AdjustTokenPrivileges(
        hToken,
        FALSE,
        &tpPrevious,
        cbPrevious,
        NULL,
        NULL
    );

    if (GetLastError() != ERROR_SUCCESS) return FALSE;

    return TRUE;
}


int
psutil_set_se_debug() {
    HANDLE hToken;
    if (! OpenThreadToken(GetCurrentThread(),
                          TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                          FALSE,
                          &hToken)
       ) {
        if (GetLastError() == ERROR_NO_TOKEN) {
            if (!ImpersonateSelf(SecurityImpersonation)) {
                CloseHandle(hToken);
                return 0;
            }
            if (!OpenThreadToken(GetCurrentThread(),
                                 TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                 FALSE,
                                 &hToken)
               ) {
                RevertToSelf();
                CloseHandle(hToken);
                return 0;
            }
        }
    }

    // enable SeDebugPrivilege (open any process)
    if (! psutil_set_privilege(hToken, SE_DEBUG_NAME, TRUE)) {
        RevertToSelf();
        CloseHandle(hToken);
        return 0;
    }

    RevertToSelf();
    CloseHandle(hToken);
    return 1;
}


int
psutil_unset_se_debug() {
    HANDLE hToken;
    if (! OpenThreadToken(GetCurrentThread(),
                          TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                          FALSE,
                          &hToken)
       ) {
        if (GetLastError() == ERROR_NO_TOKEN) {
            if (! ImpersonateSelf(SecurityImpersonation))
                return 0;
            if (!OpenThreadToken(GetCurrentThread(),
                                 TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                 FALSE,
                                 &hToken))
            {
                return 0;
            }
        }
    }

    // now disable SeDebug
    if (! psutil_set_privilege(hToken, SE_DEBUG_NAME, FALSE))
        return 0;

    CloseHandle(hToken);
    return 1;
}
