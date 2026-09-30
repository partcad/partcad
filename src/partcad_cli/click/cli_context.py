#
# OpenVMP, 2025
#
# Licensed under Apache License, Version 2.0.
#

from opentelemetry import context


class CliContext:
    def __init__(self, otel_context: context.Context, get_partcad_context, path=None):
        self.otel_context = otel_context
        self.get_partcad_context = get_partcad_context
        # The global -p/--path option (a partcad.yaml or a directory), or None
        # for the current directory. Thin commands pass it to the daemon as the
        # context URL so `context.create` loads the right workspace.
        self.path = path
