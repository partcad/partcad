import os
import threading
import time
import pickle
import base64
import sys
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import wrapper
from .exception import FileReadError

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))

class PartFactoryBrep(PartFactoryFile):
    # Constants
    MIN_SIMPLE_INFLIGHT = 1
    MIN_SUBPROCESS_FILE_SIZE = 64 * 1024  # 64 KB
    PYTHON_RUNTIME_VERSION = "3.10"

    # Shared counters for inflight operations
    lock = threading.Lock()
    count_inflight_simple = 0
    count_inflight_subprocess = 0

    def __init__(self, ctx, source_project, target_project, config):
        """
        Initialize the BREP part factory.
        """
        with pc_logging.Action("InitBREP", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".brep")
            self._create(config)
            self.runtime = None  # Lazy initialization for subprocess runtime

    async def instantiate(self, part):
        """
        Instantiate a BREP part, either using the main thread or a subprocess.
        """
        await super().instantiate(part)

        with pc_logging.Action("BREP", part.project_name, part.name):
            file_size = os.path.getsize(self.path)
            do_subprocess = self._should_use_subprocess(file_size)
            do_subprocess = True

            # Load shape via subprocess or direct method
            if do_subprocess:
                shape = await self._process_brep_subprocess()
            else:
                shape = self._load_brep_directly()

            # Update counters
            with PartFactoryBrep.lock:
                if do_subprocess:
                    PartFactoryBrep.count_inflight_subprocess -= 1
                else:
                    PartFactoryBrep.count_inflight_simple -= 1

            self.ctx.stats_parts_instantiated += 1
            return shape

    def _should_use_subprocess(self, file_size):
        """
        Determine whether to use a subprocess based on inflight counts and file size.
        """
        with PartFactoryBrep.lock:
            if (
                PartFactoryBrep.count_inflight_simple < PartFactoryBrep.MIN_SIMPLE_INFLIGHT
                or file_size < PartFactoryBrep.MIN_SUBPROCESS_FILE_SIZE
            ):
                PartFactoryBrep.count_inflight_simple += 1
                return False
            else:
                PartFactoryBrep.count_inflight_subprocess += 1
                return True

    def _load_brep_directly(self):
        """
        Load a BREP file directly in the main thread.
        """
        time.sleep(0.0001)  # Brief pause for thread synchronization
        try:
            shape = TopoDS_Shape()
            builder = BRep_Builder()
            brep_tools = BRepTools()

            if not brep_tools.Read_s(shape, self.path, builder):
                raise FileReadError(f"Failed to load BREP file: {self.path}")

            return shape
        except Exception as e:
            pc_logging.error(f"Error loading BREP file: {e}")
            raise

    async def _process_brep_subprocess(self):
        """
        Process a BREP file using a subprocess for larger files.
        """
        # Initialize runtime if not already done
        if self.runtime is None:
            pc_logging.debug("Initializing subprocess runtime...")
            self.runtime = self.ctx.get_python_runtime(self.PYTHON_RUNTIME_VERSION)
            if self.runtime is None:
                raise RuntimeError("Failed to initialize runtime for subprocess execution.")
            pc_logging.debug(f"Subprocess runtime initialized: {self.runtime}")

        wrapper_path = wrapper.get("brep.py")
        request = {"build_parameters": {}}

        # Serialize the request
        request_serialized = base64.b64encode(pickle.dumps(request)).decode()

        # Run the subprocess and handle the response
        try:
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(self.project.config_dir),
                ],
                request_serialized,
            )
            if errors:
                sys.stderr.write(errors)

            response = pickle.loads(base64.b64decode(response_serialized))
            if not response.get("success", False):
                pc_logging.error(response["exception"])
                raise PartFactoryBrepError(response["exception"])

            return response["shape"]
        except Exception as e:
            pc_logging.error(f"Subprocess execution failed: {e}")
            raise
