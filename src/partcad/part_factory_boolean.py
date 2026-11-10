#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part that is two other parts combined by a boolean operation: 'and', 'or' or 'xor'.

    parts:
      bolts:
        type: boolean
        operation: and          # and | or | xor
        parts: [hub, bolt-box]  # two references, resolved as any reference is
        whole: true             # (optional) by whole solids rather than by volume

By volume (the default) the operation is what a CAD system means by a boolean:
'and' the material both parts occupy, 'or' the material either occupies, 'xor'
the material exactly one occupies. By whole solids ('whole: true') each part is
the set of its solids, a solid of one is in the other when it lies wholly
inside it, and nothing is cut: that is what takes one piece out of a model of
several touching ones (see 'wrappers/wrapper_boolean.py').

Every face and solid of the result is in what it was in in the part it came
from - the colour, material and finish of each, carried through OCCT's history
- and the part's own CMF parameters complete it as any part's do. A boolean of
two parts is not one homogeneous body, so it takes no 'tolerance'.
"""

from . import logging as pc_logging
from . import part_factory as pf
from . import reference, sandbox_versions, shape_envelope, telemetry, wrapper
from .process_crash import describe_exit_code

OPERATIONS = ("and", "or", "xor")

# Where the two parts are recorded, resolved, on the declaration.
RESOLVED_KEY = "parts_resolved"

# What each operation is, for a part that does not describe itself.
_DESCRIBED = {
    "and": "%s and %s: the material both occupy",
    "or": "%s or %s: the material either occupies",
    "xor": "%s xor %s: the material only one of them occupies",
}
_DESCRIBED_WHOLE = {
    "and": "the solids of %s that lie inside %s",
    "or": "the solids of %s, and those of %s that do not lie inside it",
    "xor": "the solids of %s and of %s that do not lie inside the other",
}


def parse(config: dict) -> tuple:
    """'(operation, [two references], whole)' that 'config' declares; raises what is wrong with it."""
    operation = config.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("'operation' is one of %s, not %r" % (", ".join(OPERATIONS), operation))
    sources = config.get("parts")
    if (
        not isinstance(sources, list)
        or len(sources) != 2
        or not all(isinstance(source, str) and source.strip() for source in sources)
    ):
        raise ValueError("'parts' is a list of the two parts the operation combines, not %r" % (sources,))
    whole = config.get("whole", False)
    if not isinstance(whole, bool):
        raise ValueError("'whole' is true or false, not %r" % (whole,))
    return operation, [source.strip() for source in sources], whole


@telemetry.instrument()
class PartFactoryBoolean(pf.PartFactory):
    WRAPPERS = ("boolean.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitBoolean", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            self.operation, self.sources, self.whole = parse(config)
            # Resolved against the package that wrote them, as any reference is,
            # and recorded on the declaration so a listing can read them without
            # building anything. Under a key of their own: 'source_resolved' is
            # the one object an alias or an enrich stands for, and is read so.
            self.sources = [
                reference.source_of(source_project, target_project.name, {"source": source, "name": source}, "part")
                for source in self.sources
            ]
            config[RESOLVED_KEY] = list(self.sources)

            self._create(config)
            # What is combined, and how. Hashed because a shape's key is seeded
            # with nothing that identifies the shape itself (see Shape.__init__):
            # two booleans of a package differing only in their operation would
            # otherwise share one entry. What the two parts *contain* is added
            # once they are resolved (see 'prepare_async').
            self.part.hash.add_string(self.operation)
            self.part.hash.add_string("whole" if self.whole else "volume")
            for source in self.sources:
                self.part.hash.add_string(source)
            self.part.cache_dependencies_broken = True

            if not self.part.desc:
                described = _DESCRIBED_WHOLE if self.whole else _DESCRIBED
                self.part.desc = described[self.operation] % tuple(self.sources)

    def _operands(self):
        return [self.ctx.get_part(source) for source in self.sources]

    async def prepare_async(self, part) -> None:
        """Resolve the two parts, and key this one on what they contain too.

        Their names are in the key already; their content is not, and without
        it an edited part would go on being combined from the entry the old
        one produced.
        """
        broken = False
        for operand in self._operands():
            if operand is None:
                # Reported by 'instantiate', which is where a missing part of
                # an extrusion or a compound is reported too.
                return
            if not await part.add_cache_key_of(operand):
                # A part with no key - 'cache: false' - has content nothing
                # here can vouch for, so neither has what is built out of it.
                part.cacheable = False
                broken = True
        if not broken:
            part.cache_dependencies_broken = False

    async def instantiate(self, part):
        with pc_logging.Action("Boolean", part.project_name, part.name):
            try:
                envelopes = []
                for source, operand in zip(self.sources, self._operands()):
                    if operand is None:
                        part.error("%s: %s: the part %s is not found" % (part.project_name, part.name, source))
                        return None
                    envelope = await operand.get_wrapped(self.ctx)
                    if envelope is None:
                        part.error("%s: %s: the part %s produced no shape" % (part.project_name, part.name, source))
                        return None
                    envelopes.append(envelope)

                # The operation (OCCT BRepAlgoAPI) runs in a sandbox: the two
                # parts and the result cross as BREP envelopes, with the CMF
                # section each payload carries, so the core process never
                # touches a live OCP object.
                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
                await runtime.ensure_async(sandbox_versions.OCP)

                wrapper_path = wrapper.get("boolean.py")
                request = {
                    "operation": self.operation,
                    "operands": envelopes,
                    "whole": self.whole,
                    "name": "%s:%s" % (part.project_name, part.name),
                    "label": part.name,
                    # Validated and moved by the wrapper, while the shape is live (see 'Shape.finish_request').
                    shape_envelope.KEY_FINISH: part.finish_request(),
                }
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper_path, self.operation], shape_envelope.serialize(request)
                )
                if exitcode != 0 and not errors:
                    errors = "%s: %s: the boolean failed: %s" % (
                        part.project_name,
                        part.name,
                        describe_exit_code(exitcode),
                    )
                result = shape_envelope.deserialize(response_serialized) if response_serialized else None
                if result is None or not result.get("success"):
                    detail = result.get("exception") if isinstance(result, dict) else None
                    part.error("%s: %s: %s" % (part.project_name, part.name, detail or errors or "no shape"))
                    return None
                if errors:
                    # What the wrapper said on its way to a shape: CMF it could
                    # not carry, which is a warning, not a failure.
                    pc_logging.warning("%s: %s: %s" % (part.project_name, part.name, errors.strip()))

                self.ctx.stats_parts_instantiated += 1
                return result["shape"]
            except Exception as e:
                part.error("%s: %s: failed to combine the two parts: %s" % (part.project_name, part.name, e))
                pc_logging.exception("Failed to create a boolean part: %s" % e)
                return None
