#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from contextlib import asynccontextmanager, contextmanager
import inspect
from opentelemetry import trace, context
from opentelemetry.trace import Tracer
import os

from . import telemetry_none
from . import telemetry_sentry

partcad_version = None
tracer: Tracer | None  # To be initialized in telemetry_init()
tracer_onced = False


def init(version: str):
    global partcad_version
    partcad_version = version

    global tracer
    tracer = telemetry_none.init_none()


def once():
    global tracer_onced
    if tracer_onced:
        return
    tracer_onced = True

    global tracer, partcad_version

    if not os.getenv("PYTEST_VERSION"):
        # TODO(clairbee): add suport for alternate telemetry backends
        tracer = telemetry_sentry.init_sentry(partcad_version)
    else:
        # Do not collect telemetry data for pytest as it's mostly short meaningless transactions
        # It is already of type "none"
        # tracer = telemetry_none.init_none()
        pass


@asynccontextmanager
async def start_as_current_span_async(name, **kwargs):
    once()

    global tracer
    with tracer.start_as_current_span(name, **kwargs) as span:
        yield span


@contextmanager
def start_as_current_span(name: str, **kwargs):
    once()

    global tracer
    with tracer.start_as_current_span(name, **kwargs) as span:
        yield span


@contextmanager
def set_context(ctx):
    token = context.attach(ctx)
    yield token
    context.detach(token)


def instrument_span(name, category: str = ""):
    once()

    global tracer

    def decorator(func, attr_getter):
        def wrapper(*args, **kwargs):
            parent = trace.get_current_span()
            tag = name if not category else f"{category}.{name}"
            if getattr(parent, "tag", "") == tag:
                return func(*args, **kwargs)
            with tracer.start_as_current_span(tag) as span:
                for k, v in attr_getter(*args, **kwargs).items():
                    span.set_attribute(k, v)
                setattr(span, "tag", tag)
                for arg in args:
                    if isinstance(arg, (str, int, float, bool)):
                        span.set_attribute(
                            f"{func.__code__.co_varnames[args.index(arg)]}",
                            arg,
                        )

                for key, value in kwargs.items():
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(key, value)
                return func(*args, **kwargs)

        return wrapper

    return decorator


def instrument_span_async(name, category: str = ""):
    once()

    def decorator(func, attr_getter):
        async def wrapper(*args, **kwargs):
            parent = trace.get_current_span()
            tag = name if not category else f"{category}.{name}"
            if getattr(parent, "tag", "") == tag:
                return await func(*args, **kwargs)
            # TODO(clairbee): what's the benefit of using "async with" here?
            async with start_as_current_span_async(tag) as span:
                for k, v in attr_getter(*args, **kwargs).items():
                    span.set_attribute(k, v)
                setattr(span, "tag", tag)
                for arg in args:
                    if isinstance(arg, (str, int, float, bool)):
                        span.set_attribute(
                            f"{func.__code__.co_varnames[args.index(arg)]}",
                            arg,
                        )

                for key, value in kwargs.items():
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(key, value)
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def instrument(exclude: list | None = None, attr_getters=None):
    if exclude is None:
        exclude = []
    if attr_getters is None:
        attr_getters = lambda attr_value: lambda *args, **kwargs: {}

    def decorator(cls):
        for attr_name, attr_value in vars(cls).items():
            if callable(attr_value) and not inspect.isclass(attr_value) and attr_name not in exclude:
                if inspect.iscoroutinefunction(attr_value):
                    setattr(
                        cls,
                        attr_name,
                        instrument_span_async(attr_name, cls.__name__)(attr_value, attr_getters(attr_name)),
                    )
                else:
                    setattr(
                        cls,
                        attr_name,
                        instrument_span(attr_name, cls.__name__)(attr_value, attr_getters(attr_name)),
                    )
        return cls

    return decorator
