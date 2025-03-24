#
# OpenVMP, 2025
#
# Licensed under Apache License, Version 2.0.
#

from opentelemetry import context


class CliContext:
    def __init__(self, otel_context: context.Context, get_partcad_context):
        self.otel_context = otel_context
        self.get_partcad_context = get_partcad_context
