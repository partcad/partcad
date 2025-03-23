#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from contextlib import contextmanager
from opentelemetry.trace import Tracer, Span


class NoneSpan(Span):
    def __init__(self):
        pass

    def end(self):
        pass

    def add_event(self, name, attributes=None, timestamp=None):
        pass

    def get_span_context(self):
        pass

    def is_recording(self):
        pass

    def record_exception(self, exception, attributes=None, timestamp=None, escaped=False):
        pass

    def set_attributes(self, attributes):
        pass

    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def update_name(self, name):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class NoneTracer(Tracer):
    @contextmanager
    def start_as_current_span(self, *args, **kwargs):
        yield NoneSpan()

    def start_span(self, *args, **kwargs):
        return None

    def get_current_span(self):
        return None

    def get_tracer(self, *args, **kwargs):
        return None

    def shutdown(self, *args, **kwargs):
        pass


def init_none() -> Tracer:
    return NoneTracer()
