#!/usr/bin/env python
# -*- coding:utf-8 -*-

import sys
import multiprocessing

try:
    if sys.version_info.major < 3:
        import concurrent27.futures as concurrent
    else:
        import concurrent.futures as concurrent
except ImportError:
    pass



def default_n():
    return multiprocessing.cpu_count()

n = default_n()

if 'concurrent' in globals():
    pool = concurrent.ThreadPoolExecutor(max_workers=n)
else:
    pool = None
callbacks = []
results = []


def run(f, *args, **kwargs):

    if pool:
        pool._max_workers = n
        pool._adjust_thread_count()

        f = pool.submit(f, *args, **kwargs)
    results.append(f)

    return f


def task(f, *args, **kwargs):
    def do_task():
        result = run(f, *args, **kwargs)
        results.append(result)

        for cb in callbacks:
            result.add_done_callback(cb)

        return result
    return do_task


def callback(f):
    callbacks.append(f)

    def register_callback():
        f()

    return register_callback