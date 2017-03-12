/*
 * Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include <Python.h>
#include <Winsvc.h>

SC_HANDLE psutil_get_service_handle(
char service_name, DWORD scm_access, DWORD access);
PyObject *psutil_winservice_enumerate(PyObject *self, PyObject *args);
PyObject *psutil_winservice_query_config(PyObject *self, PyObject *args);
PyObject *psutil_winservice_query_status(PyObject *self, PyObject *args);
PyObject *psutil_winservice_query_descr(PyObject *self, PyObject *args);
PyObject *psutil_winservice_start(PyObject *self, PyObject *args);
PyObject *psutil_winservice_stop(PyObject *self, PyObject *args);
