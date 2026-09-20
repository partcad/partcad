#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import inspect
import os
from contextlib import asynccontextmanager, contextmanager

from opentelemetry import context, trace
from opentelemetry.trace import Tracer

from . import telemetry_none, telemetry_sentry

partcad_version = None
# Annotation *and* an initialiser: a bare annotation binds no name, so before
# `init()`/`once()` ran, `tracer` did not exist at module scope at all and the
# readers below only resolved it because each declared `global tracer`.
tracer: Tracer | None = None  # To be initialized in telemetry_init()
tracer_onced = False


def init(version: str):
    global partcad_version
    partcad_version = version

    global tracer
    tracer = telemetry_none.init_none()


def collecting() -> bool:
    """Whether telemetry is to be collected at all in this process.

    The configured 'telemetry.type' - 'pc system set telemetry type none',
    'telemetry: type: none' in the configuration, or PC_TELEMETRY_TYPE - is what
    says. It is documented as the way to turn telemetry off (see
    'docs/source/features.rst') and was written, read back by 'pc system
    telemetry info' and then never consulted by anything that collects: 'once()'
    initialized Sentry regardless, and the only thing that ever stopped it was
    leaving the Sentry DSN empty, which is not what any of the three documented
    switches does.

    That is not only a setting that did nothing. Instrumentation is not free:
    every object a package declares is created through a dozen instrumented
    methods, and each of those is an OpenTelemetry span the Sentry span
    processor then handles - some 28 spans per part, which is most of the time
    'pc list -r' spends loading a large catalog. A user who has opted out is
    paying for spans that were opted out of.

    Anything other than 'none' is a backend to collect with; 'sentry' is the
    only one implemented, and is the default.
    """
    # Imported here rather than at the top: the configuration reads the user's
    # config file, and this module is imported by everything.
    from .user_config import user_config

    return user_config.telemetry_config.type != "none"


def once():
    global tracer_onced
    if tracer_onced:
        return
    tracer_onced = True

    global tracer

    if os.getenv("PYTEST_VERSION"):
        # Do not collect telemetry data for pytest as it's mostly short meaningless transactions
        # It is already of type "none"
        # tracer = telemetry_none.init_none()
        return

    if not collecting():
        # Opted out. Explicitly rather than by leaving 'tracer' as it is: 'once()'
        # can run before 'init()' has, and 'tracer' is then still None.
        tracer = telemetry_none.init_none()
        return

    # TODO(clairbee): add suport for alternate telemetry backends
    tracer = telemetry_sentry.init_sentry(partcad_version)


@asynccontextmanager
async def start_as_current_span_async(name, **kwargs):
    once()

    with tracer.start_as_current_span(name, **kwargs) as span:
        yield span


@contextmanager
def start_as_current_span(name: str, **kwargs):
    once()

    with tracer.start_as_current_span(name, **kwargs) as span:
        yield span


@contextmanager
def set_context(ctx):
    token = context.attach(ctx)
    yield token
    context.detach(token)


def instrument_span(name, category: str = ""):
    once()

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
