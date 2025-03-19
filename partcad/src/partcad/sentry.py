import inspect
from opentelemetry import trace
from contextlib import asynccontextmanager
from opentelemetry import trace

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
