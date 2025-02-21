import os
import threading
import time
import pickle
import base64
import sys
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import wrapper
from .exception import PartFactoryError

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))

class PartFactoryObj(PartFactoryFile):
    MIN_SIMPLE_INFLIGHT = 1
    MIN_SUBPROCESS_FILE_SIZE = 64 * 1024  # 64 KB
    PYTHON_RUNTIME_VERSION = "3.10"

    lock = threading.Lock()
    count_inflight_simple = 0
    count_inflight_subprocess = 0

    def __init__(self, ctx, source_project, target_project, config):
        """
        Initialize the OBJ part factory.
        """
        with pc_logging.Action("InitOBJ", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".obj", can_create=False)
            self._create(config)
            self.runtime = None  # Lazy initialization for subprocess runtime

    async def instantiate(self, part):
        """
        Instantiate an OBJ part, either using the main thread or a subprocess.
        """
        await super().instantiate(part)

        with pc_logging.Action("OBJ", part.project_name, part.name):
            file_size = os.path.getsize(self.path)
            do_subprocess = self._should_use_subprocess(file_size)

            # Load shape via subprocess or direct method
            if do_subprocess:
                shape = await self._process_obj_subprocess()
            else:
                shape = self._load_obj_directly()

            if not isinstance(shape, TopoDS_Compound):
                shape = self._create_compound(shape)

            # Update counters
            with PartFactoryObj.lock:
                if do_subprocess:
                    PartFactoryObj.count_inflight_subprocess -= 1
                else:
                    PartFactoryObj.count_inflight_simple -= 1

            self.ctx.stats_parts_instantiated += 1
            return shape

    def _should_use_subprocess(self, file_size):
        """
        Determine whether to use a subprocess based on inflight counts and file size.
        """
        with PartFactoryObj.lock:
            if (
                PartFactoryObj.count_inflight_simple < PartFactoryObj.MIN_SIMPLE_INFLIGHT
                or file_size < PartFactoryObj.MIN_SUBPROCESS_FILE_SIZE
            ):
                PartFactoryObj.count_inflight_simple += 1
                return False
            else:
                PartFactoryObj.count_inflight_subprocess += 1
                return True

    def _load_obj_directly(self):
        """
        Load an OBJ file directly in the main thread.
        """
        time.sleep(0.0001)  # Brief pause for thread synchronization
        try:
            vertices = []
            faces = []

            with open(self.path, 'r') as file:
                for line in file:
                    if line.startswith('#'):
                        continue
                    if line.startswith('v '):
                        parts = line.strip().split()
                        vertex = tuple(map(float, parts[1:]))
                        vertices.append(vertex)
                    elif line.startswith('f '):
                        parts = line.strip().split()
                        face = [int(part.split('/')[0]) for part in parts[1:]]
                        faces.append(face)

            shape_faces = []
            for face in faces:
                polygon = BRepBuilderAPI_MakePolygon()
                for vertex_idx in face:
                    x, y, z = vertices[vertex_idx - 1]
                    polygon.Add(gp_Pnt(x, y, z))
                polygon.Close()
                shape_faces.append(BRepBuilderAPI_MakeFace(polygon.Wire()).Face())

            return self._create_compound(shape_faces)
        except Exception as e:
            pc_logging.error(f"Error loading OBJ file: {e}")
            raise

    async def _process_obj_subprocess(self):
        """
        Process an OBJ file using a subprocess for larger files.
        """
        # Initialize runtime if not already done
        if self.runtime is None:
            pc_logging.debug("Initializing subprocess runtime...")
            self.runtime = self.ctx.get_python_runtime(self.PYTHON_RUNTIME_VERSION)
            if self.runtime is None:
                raise RuntimeError("Failed to initialize runtime for subprocess execution.")
            pc_logging.debug(f"Subprocess runtime initialized: {self.runtime}")

        wrapper_path = wrapper.get("obj.py")
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
                raise PartFactoryError(response["exception"])

            shape = response["shape"]
            if isinstance(shape, list):
                shape = self._create_compound(shape)
            return shape
        except Exception as e:
            pc_logging.error(f"Subprocess execution failed: {e}")
            raise

    def _create_compound(self, faces):
        """
        Convert a list of TopoDS_Face objects into a TopoDS_Compound.
        """
        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for face in faces:
            builder.Add(compound, face)
        return compound
