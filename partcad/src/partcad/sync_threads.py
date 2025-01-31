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
from opentelemetry import context as otel_context
from opentelemetry.trace import Tracer
from typing import Callable

from .sentry import tracer
from .user_config import user_config

class TracedThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, tracer: Tracer, *args, **kwargs):
        self.tracer = tracer
        super().__init__(*args, **kwargs)

    def with_otel_context(self, context: otel_context.Context, fn: Callable):
        otel_context.attach(context)
        return fn()

    def submit(self, fn, *args, **kwargs):
        # get the current otel context
        context = otel_context.get_current()
        if context:
            return super().submit(
                lambda: self.with_otel_context(context, lambda: fn(*args, **kwargs)),
            )
        else:
            return super().submit(lambda: fn(*args, **kwargs))

if user_config.threads_max is not None:
    cpu_count = user_config.threads_max
else:
    cpu_count = os.cpu_count()
    if cpu_count < 8:
        # This is a workaround for the fact that sometimes we waste threads and
        # we should not dead lock ourselves on a machine with a small number of cores
        cpu_count = 7
    else:
        # Leave one core for the asyncio event loop and stuff
        cpu_count = cpu_count - 1

constrained_cpu_count = cpu_count
unconstrained_cpu_count = 2 + cpu_count * 2

if os.name == "nt":
    # Windows has a limit of 61 threads per executor
    if constrained_cpu_count > 61:
        constrained_cpu_count = 61
    if unconstrained_cpu_count > 61:
        unconstrained_cpu_count = 61

executor = TracedThreadPoolExecutor(tracer, constrained_cpu_count, "partcad-executor-")
others = TracedThreadPoolExecutor(tracer, unconstrained_cpu_count, "partcad-executor-others-")


# run returns a future to wait for 'method' to be completed in a separate thread on the constrained executor
async def run(method, *args):
    global executor

    return await asyncio.get_running_loop().run_in_executor(executor, method, *args)


# run returns a future to wait for 'method' to be completed in a separate thread
async def run_detached(method, *args):
    global others

    return await asyncio.get_running_loop().run_in_executor(others, method, *args)


# run returns a future to wait for 'coroutine' to be completed in a separate thread on a constrained executor
async def run_async(coroutine, *args):
    global executor

    def method():
        return asyncio.run(coroutine(*args))

    return await asyncio.get_running_loop().run_in_executor(executor, method)


# run returns a future to wait for 'coroutine' to be completed in a separate thread
async def run_async_detached(coroutine, *args):
    global others

    def method():
        return asyncio.run(coroutine(*args))

    return await asyncio.get_running_loop().run_in_executor(others, method)
