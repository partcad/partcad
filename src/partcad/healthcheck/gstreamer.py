#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this machine can encode the videos '//builtin/render' writes.

The video file types ('mp4', 'mov', 'webm', ...) draw their frames in the
sandbox and hand them to GStreamer, which pip cannot install. Where the 'docker'
or 'remote' sandbox renders, they run in PartCAD's GStreamer image and nothing
is needed here; in any other sandbox it is the machine's own 'gst-launch-1.0' -
even on a machine with Docker running, when its owner chose that sandbox.

Reported and not failed, like a missing conda: a machine that renders no video
is not a broken machine. What it finds is what a video render would say before
drawing anything -- the lookup is the renderer's own ('video_encode.find_tool'),
loaded from the built-in package rather than copied, so the two cannot come to
disagree about where GStreamer is.
"""

import importlib.util
import os

from partcad import output
from partcad import runtime as pc_runtime
from partcad.user_config import user_config

from .tests import SEVERITY_WARNING, HealthCheckReport, HealthCheckTest

# The elements the default file types need: H.264 in MP4, VP9 in WebM, the text
# over the picture, the logo, and what reads back an appended video. A
# GStreamer without one of them writes some videos and not others, which is
# worth knowing before a render says so.
ELEMENTS = ("x264enc", "mp4mux", "vp9enc", "webmmux", "textoverlay", "gdkpixbufoverlay", "avenc_aac")


def _sandbox() -> str:
    """The sandbox a video renders in here, picked as 'Context.preferred_python_sandbox' picks it.

    A machine with Docker running whose owner chose 'venv' renders on the
    host, and needs the host's GStreamer.
    """
    if user_config.python_sandbox_declared:
        return user_config.python_sandbox
    if getattr(user_config, "use_docker_python_declared", False):
        return "docker"
    return "docker" if pc_runtime.docker_enabled() else user_config.python_sandbox


def _video_encode():
    """'//builtin/render/video_encode.py', the module the video renderer finds GStreamer with."""
    path = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]], "video_encode.py")
    spec = importlib.util.spec_from_file_location("partcad_builtin_render_video_encode", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GStreamerCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="GStreamer",
            tags=["gstreamer", "video", "render"],
            description="check that the video file types of 'pc render' have GStreamer to encode with",
            severity=SEVERITY_WARNING,
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        self.findings = []
        sandbox = _sandbox()
        if sandbox == "remote" or (sandbox == "docker" and pc_runtime.docker_enabled()):
            # These run the video file types in PartCAD's GStreamer image -
            # 'remote' on its own machine: nothing here is used.
            report = HealthCheckReport(self.name, self.findings, False)
            report.debug("The '%s' sandbox encodes videos in PartCAD's GStreamer image" % sandbox)
            return report
        encode = _video_encode()
        launcher = encode.find_tool(encode.LAUNCH)
        if launcher is None:
            self.findings.append(encode.MISSING % (encode.LAUNCH, encode.ENV_VAR))
            return HealthCheckReport(self.name, self.findings, False)
        # The discoverer reads back where an appended video's turn stopped, and
        # Debian packages it apart from 'gst-launch-1.0' (plugins-base-apps).
        if encode.find_tool(encode.DISCOVERER) is None:
            self.findings.append(
                "There is no '%s' beside the GStreamer at %s: a video appended to fails. On Debian and Ubuntu "
                "it is in gstreamer1.0-plugins-base-apps." % (encode.DISCOVERER, launcher)
            )
        missing = [element for element in ELEMENTS if not encode.has_element(element)]
        if missing:
            self.findings.append(
                "The GStreamer at %s has no %s: the video file types that need %s fail. Install its "
                "'good', 'bad', 'ugly' and 'libav' plugins, and the Pango text overlay."
                % (launcher, ", ".join(missing), "it" if len(missing) == 1 else "them")
            )
        report = HealthCheckReport(self.name, self.findings, False)
        report.debug("Using the GStreamer at %s" % launcher)
        return report

    def fix(self) -> bool:
        return False
