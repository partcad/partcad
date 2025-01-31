import inspect
import logging
from opentelemetry import trace
from contextlib import asynccontextmanager
import sentry_sdk
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.propagate import set_global_textmap
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.opentelemetry import SentrySpanProcessor, SentryPropagator

from .user_config import user_config


def init_sentry(version: str) -> None:
    if not sentry_sdk.is_initialized() and user_config.sentry_config.dsn:
        critical_to_ignore = [
            "action_start: ",
            "action_end: ",
        ]
        debug_to_ignore = [
            "Starting action",
            "Finished action",
        ]

        def before_send(event, hint):
            # Reduce noise in logs (drop events from "with logging.Process():")
            if event.get("level") == "critical":
                # from logging_ansi_terminal.py
                message = event.get("logentry", {}).get("message")
                if message and message.startswith(critical_to_ignore):
                    return None
            elif event.get("level") == "debug":
                # from logging.py
                message = event.get("logentry", {}).get("message")
                if message and message.startswith(debug_to_ignore):
                    return None

            return event

        sentry_sdk.init(
            dsn=user_config.sentry_config.dsn,
            release=version,
            debug=user_config.sentry_config.debug,
            shutdown_timeout=user_config.sentry_config.shutdown_timeout,
            enable_tracing=True,
            attach_stacktrace=False,
            traces_sample_rate=user_config.sentry_config.traces_sample_rate,
            integrations=[
                LoggingIntegration(
                    level=logging.ERROR,
                ),
            ],
            before_send=before_send,
            instrumenter="otel",
        )

        provider = TracerProvider()
        provider.add_span_processor(SentrySpanProcessor())
        trace.set_tracer_provider(provider)
        set_global_textmap(SentryPropagator())


tracer = trace.get_tracer("PartCAD")


@asynccontextmanager
async def start_as_current_span_async(name, **kwargs):
    with tracer.start_as_current_span(name, **kwargs) as span:
        yield span


def start_span_as(name, category: str = ""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            parent = trace.get_current_span()
            tag = name if not category else f"{category}.{name}"
            if getattr(parent, "tag", "") == tag:
                return func(*args, **kwargs)
            with tracer.start_as_current_span(tag) as span:
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


def start_span_as_async(name, category: str = ""):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            parent = trace.get_current_span()
            tag = name if not category else f"{category}.{name}"
            if getattr(parent, "tag", "") == tag:
                return await func(*args, **kwargs)
            async with start_as_current_span_async(tag) as span:
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


def instrument(exclude: list = []):
    def decorator(cls):
        for attr_name, attr_value in vars(cls).items():
            if callable(attr_value) and not inspect.isclass(attr_value) and attr_name not in exclude:
                if inspect.iscoroutinefunction(attr_value):
                    setattr(cls, attr_name, start_span_as_async(attr_name, cls.__name__)(attr_value))
                else:
                    setattr(cls, attr_name, start_span_as(attr_name, cls.__name__)(attr_value))
        return cls

    return decorator
