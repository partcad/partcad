#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-02-09
#
# Licensed under Apache License, Version 2.0.
import os
from concurrent.futures import ThreadPoolExecutor
from opentelemetry import context as otel_context
from opentelemetry.trace import Tracer
from typing import Callable
import asyncio

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


class ThreadPoolManager:
    def __init__(self, threads_max: int):
        # Calculate CPU count based on user config or system capabilities
        if threads_max is not None:
            cpu_count = threads_max
        else:
            cpu_count = os.cpu_count() or 1  # Handle None case
            if cpu_count < 8:
                cpu_count = 7  # Workaround for small core counts
            else:
                cpu_count -= 1  # Leave one core for system

        # Calculate thread counts
        constrained = cpu_count
        unconstrained = 2 + cpu_count * 2

        # Windows thread limit adjustment
        if os.name == "nt":
            constrained = min(constrained, 61)
            unconstrained = min(unconstrained, 61)

        # Create executors
        self.constrained_executor = TracedThreadPoolExecutor(
            tracer,
            constrained, "partcad-executor-"
        )
        self.unconstrained_executor = TracedThreadPoolExecutor(
            tracer,
            unconstrained, "partcad-executor-others-"
        )

    async def run(self, method, *args):
        """Run in constrained executor"""
        return await asyncio.get_running_loop().run_in_executor(
            self.constrained_executor, method, *args
        )

    async def run_detached(self, method, *args):
        """Run in unconstrained executor"""
        return await asyncio.get_running_loop().run_in_executor(
            self.unconstrained_executor, method, *args
        )

    async def run_async(self, coroutine, *args):
        """Run async coroutine in constrained executor"""
        def sync_wrapper():
            return asyncio.run(coroutine(*args))
        return await self.run(sync_wrapper)

    async def run_async_detached(self, coroutine, *args):
        """Run async coroutine in unconstrained executor"""
        def sync_wrapper():
            return asyncio.run(coroutine(*args))
        return await self.run_detached(sync_wrapper)


threadpool_manager = ThreadPoolManager(user_config.threads_max)
