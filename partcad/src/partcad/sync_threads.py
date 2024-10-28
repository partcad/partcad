#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-02-09
#
# Licensed under Apache License, Version 2.0.

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import sys

cpu_count = os.cpu_count()
# Leave one core for the asyncio event loop and stuff
if cpu_count > 1:
    cpu_count -= 1
if cpu_count < 3:
    cpu_count = 3
executor = ThreadPoolExecutor(cpu_count, "partcad-executor-")


# run returns a future to wait for 'method' to be completed in a separate thread
async def run(method, *args):
    global executor

    if (
        sys.version_info[0] == 3 and sys.version_info[1] >= 10
    ) or sys.version_info[0] > 3:
        return await asyncio.get_running_loop().run_in_executor(
            executor, method, *args
        )
    else:
        # Python 3.9 and lower has a buggy '.run_in_executor()'.
        # It crashes with:
        # `got Future <Future pending> attached to a different loop`
        # TODO(clairbee): consider simply spawning a thread and waiting for completion
        return method(*args)


# run returns a future to wait for 'coroutine' to be completed in a separate thread
async def run_async(coroutine, *args):
    global executor

    def method():
        return asyncio.run(coroutine(*args))

    if (
        sys.version_info[0] == 3 and sys.version_info[1] >= 10
    ) or sys.version_info[0] > 3:
        return await asyncio.get_running_loop().run_in_executor(
            executor, method
        )
    else:
        # Python 3.9 and lower has a buggy '.run_in_executor()'.
        # It crashes with:
        # `got Future <Future pending> attached to a different loop`
        # TODO(clairbee): consider simply spawning a thread and waiting for completion
        return asyncio.run(coroutine(*args))
