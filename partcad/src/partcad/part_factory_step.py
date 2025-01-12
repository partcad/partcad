#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from OCP.TopoDS import (
    TopoDS_Builder,
    TopoDS_Compound,
)
import OCP.IFSelect
from OCP.STEPControl import STEPControl_Reader

import base64
import os
import pickle
import sys
import threading
import time

from . import logging as pc_logging
from . import wrapper
from .part_factory_file import PartFactoryFile

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper

# TODO(clairbee): revisit whether it still provides any performance benefits
#                 in Python 3.13+ (is GIL still a problem?)


class PartFactoryStep(PartFactoryFile):
    # How many STEP files should be loaded directly simultaneously (without
    # launching a subprocess), no matter the file size.
    MIN_SIMPLE_INFLIGHT = 1

    # How big of a STEP file is needed to consider launching a sub-process.
    MIN_SUBPROCESS_FILE_SIZE = 64 * 1024

    # lock is used to protect changes to the static class members
    lock = threading.Lock()
    # How many of the current instances are in which mode?
    count_inflight_simple = 0
    count_inflight_subprocess = 0

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTEP", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".step",
            )
            # Complement the config object here if necessary
            self._create(config)

            self.runtime = None

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STEP", part.project_name, part.name):
            do_subprocess = False

            file_size = os.path.getsize(self.path)

            with PartFactoryStep.lock:
                if (
                    PartFactoryStep.count_inflight_simple < PartFactoryStep.MIN_SIMPLE_INFLIGHT
                    or file_size < PartFactoryStep.MIN_SUBPROCESS_FILE_SIZE
                ):
                    PartFactoryStep.count_inflight_simple += 1
                else:
                    do_subprocess = True
                    PartFactoryStep.count_inflight_subprocess += 1
                    if self.runtime == None:
                        # We don't care about customer preferences much here
                        # as this is expected to be hermetic.
                        # Stick to the version where CadQuery is known to work.
                        self.runtime = self.ctx.get_python_runtime("3.10")

            if do_subprocess:
                wrapper_path = wrapper.get("step.py")

                request = {"build_parameters": {}}
                register_ocp_helper()
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
                register_ocp_helper()
                result = pickle.loads(response)

                if not result["success"]:
                    pc_logging.error(result["exception"])
                    raise Exception(result["exception"])
                shape = result["shape"]
            else:
                # Thanks for OCP deficiencies in handling of GIL,
                # as soon as 'importStep()' is called, all of other Python
                # threads are going to be frozen, so we need to give other
                # threads an opportunity to spawn processes to stay busy during
                # the 'importStep()' call.
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                time.sleep(0.0001)
                # TODO(clairbee): remove sleep calls when GIL is fixed in CQ

                reader = STEPControl_Reader()

                readStatus = reader.ReadFile(self.path)
                if readStatus != OCP.IFSelect.IFSelect_RetDone:
                    raise ValueError("STEP File could not be loaded")
                for i in range(reader.NbRootsForTransfer()):
                    reader.TransferRoot(i + 1)

                builder = TopoDS_Builder()
                compound = TopoDS_Compound()
                builder.MakeCompound(compound)
                for i in range(reader.NbShapes()):
                    occ_shape = reader.Shape(i + 1)
                    builder.Add(compound, occ_shape)
                shape = compound

            with PartFactoryStep.lock:
                if do_subprocess:
                    PartFactoryStep.count_inflight_subprocess -= 1
                else:
                    PartFactoryStep.count_inflight_simple -= 1

            self.ctx.stats_parts_instantiated += 1

            return shape
