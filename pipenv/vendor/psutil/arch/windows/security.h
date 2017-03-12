/*
 * Copyright (c) 2009, Jay Loden, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Security related functions for Windows platform (Set privileges such as
 * SeDebug), as well as security helper functions.
 */

#include <windows.h>

BOOL psutil_set_privilege(HANDLE hToken, LPCTSTR Privilege, BOOL bEnablePrivilege);
HANDLE psutil_token_from_handle(HANDLE hProcess);
int psutil_has_system_privilege(HANDLE hProcess);
int psutil_set_se_debug();
int psutil_unset_se_debug();

