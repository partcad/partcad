from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
import base64
import os
import pickle
import threading
import time
import sys

from . import logging as pc_logging
from . import wrapper
from .part_factory_file import PartFactoryFile


class PartFactoryBrep(PartFactoryFile):
    MIN_SIMPLE_INFLIGHT = 1
    MIN_SUBPROCESS_FILE_SIZE = 64 * 1024

    lock = threading.Lock()
    count_inflight_simple = 0
    count_inflight_subprocess = 0

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitBREP", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".brep",
            )
            self._create(config)
            self.runtime = None

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("BREP", part.project_name, part.name):
            do_subprocess = False
            file_size = os.path.getsize(self.path)

            with PartFactoryBrep.lock:
                if (
                    PartFactoryBrep.count_inflight_simple < PartFactoryBrep.MIN_SIMPLE_INFLIGHT
                    or file_size < PartFactoryBrep.MIN_SUBPROCESS_FILE_SIZE
                ):
                    PartFactoryBrep.count_inflight_simple += 1
                else:
                    do_subprocess = True
                    PartFactoryBrep.count_inflight_subprocess += 1
                    if self.runtime is None:
                        self.runtime = self.ctx.get_python_runtime("3.10")

            if do_subprocess:
                wrapper_path = wrapper.get("brep.py")

                if self.runtime is None:
                    pc_logging.debug("Initializing runtime...")
                    self.runtime = self.ctx.get_python_runtime("3.10")
                    if self.runtime is None:
                        raise RuntimeError("Failed to initialize runtime for subprocess execution.")
                    pc_logging.debug(f"Runtime initialized: {self.runtime}")

                request = {"build_parameters": {}}
                picklestring = pickle.dumps(request)
                request_serialized = base64.b64encode(picklestring).decode()

                response_serialized, errors = await self.runtime.run_async(
                    [
                        wrapper_path,
                        os.path.abspath(self.path),
                        os.path.abspath(self.project.config_dir),
                    ],
                    request_serialized,
                )
                sys.stderr.write(errors)

                response = base64.b64decode(response_serialized)
                result = pickle.loads(response)

                if not result["success"]:
                    pc_logging.error(result["exception"])
                    raise Exception(result["exception"])
                shape = result["shape"]
            else:
                time.sleep(0.0001)
                try:
                    shape = TopoDS_Shape()
                    builder = BRep_Builder()
                    brep_tools = BRepTools()

                    if not brep_tools.Read_s(shape, self.path, builder):
                        raise ValueError("BRep file could not be loaded")
                except Exception as e:
                    pc_logging.error(f"Error loading BRep file: {e}")
                    raise

            with PartFactoryBrep.lock:
                if do_subprocess:
                    PartFactoryBrep.count_inflight_subprocess -= 1
                else:
                    PartFactoryBrep.count_inflight_simple -= 1

            self.ctx.stats_parts_instantiated += 1

            return shape
