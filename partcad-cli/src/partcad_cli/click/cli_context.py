#
# OpenVMP, 2025
#
# Licensed under Apache License, Version 2.0.
#

from opentelemetry import context


class CliContext:
    def __init__(self, otel_context: context.Context):
        self.otel_context = otel_context
        self.get_partcad_context = lambda: None
