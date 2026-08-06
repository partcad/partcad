#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import uuid
import platform
import psutil
import sentry_sdk
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.propagate import set_global_textmap
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.opentelemetry import SentrySpanProcessor, SentryPropagator
import sentry_sdk.types

from . import logging


class PartcadSentrySpanProcessor(SentrySpanProcessor):
    def _update_transaction_with_otel_data(self, sentry_span, otel_span):
        super()._update_transaction_with_otel_data(sentry_span, otel_span)
        if otel_span.attributes.get("action"):
            # Make the transactions look different in the Sentry web UI
            sentry_span.name = otel_span.attributes.get("action")

    def _update_span_with_otel_data(self, sentry_span, otel_span):
        super()._update_span_with_otel_data(sentry_span, otel_span)
        # Reduce volume of logs
        sentry_span.description = ""


def init_sentry(version: str) -> None:
    from .user_config import user_config

    tc = user_config.telemetry_config

    # TODO(clairbee): use an on/off switch in the user_config
    if not tc.sentry_dsn:
        # Fall back to "none" if no DSN
        from . import telemetry_none

        return telemetry_none.init_none()

    # The following must be tuples for startswith() to work
    critical_to_ignore = (
        "action_start: ",
        "action_end: ",
        "process_start: ",
        "process_end: ",
    )
    debug_to_ignore = (
        "Starting action",
        "Finished action",
    )

    def before_send(event: sentry_sdk.types.Event, hint):
        # Reduce noise in logs (drop events from "with logging.Process():")
        message: str
        if event.get("level") == "critical" or event.get("level") == "fatal":
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
        dsn=tc.sentry_dsn,
        release=version,
        environment=tc.env,
        debug=tc.debug,
        shutdown_timeout=tc.sentry_shutdown_timeout,
        attach_stacktrace=tc.sentry_attach_stacktrace,
        traces_sample_rate=tc.sentry_traces_sample_rate,
        default_integrations=False,
        profiles_sample_rate=1.0,
        integrations=[
            LoggingIntegration(
                level=logging.ERROR,
            ),
        ],
        before_send=before_send,
        instrumenter="otel",
    )

    # Generate a random ID for the user
    cfg_dir = user_config.get_config_dir()
    guid_file = os.path.join(cfg_dir, ".generated_id")
    # Check if the ID is already cached
    if os.path.exists(guid_file):
        with open(guid_file, "r") as f:
            unique_uid = f.read().strip()
    else:
        # Generate a new random ID and cache it
        unique_uid = str(uuid.uuid4())
        with open(guid_file, "w") as f:
            f.write(unique_uid)

    sentry_sdk.set_user({"id": unique_uid})
    # Override the default server_name tag
    sentry_sdk.set_tag("server_name", unique_uid)
    sentry_sdk.set_tag("env.remote_containers", os.environ.get("REMOTE_CONTAINERS", "false").lower() == "true")

    system = platform.system()
    release = platform.release()
    machine = platform.machine()
    arch = platform.architecture()[0]
    sentry_sdk.set_tag("os.name", f"{system} {release} {machine} {arch}")

    if tc.performance or tc.failures:
        # https://docs.sentry.io/product/performance/metrics/#custom-performance-measurements
        # https://docs.sentry.io/platforms/python/tracing/instrumentation/performance-metrics/
        memory_rss = psutil.Process().memory_info().rss
        cpu_user = psutil.Process().cpu_times().user
        sentry_sdk.set_measurement("memory.rss", memory_rss, "byte")
        sentry_sdk.set_measurement("cpu.user", cpu_user, "second")

    if tc.performance:
        # Collect spans to measure performance
        provider = TracerProvider()
        provider.add_span_processor(PartcadSentrySpanProcessor())
        trace.set_tracer_provider(provider)
        set_global_textmap(SentryPropagator())

    return trace.get_tracer("PartCAD")
