#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The factories that produce scenes.

A scene is built the way an assembly is, out of the same files, so every one of
these is the matching assembly factory with three class attributes changed:
which kind the package registers the object under, which class holds it, and
which pair of context counters it is tallied in (see 'AssemblyFactory'). That
is deliberate and is the whole point -- an ASSY file read as a scene and the
same file read as an assembly must produce the same tree, and two readers of
one format would eventually stop doing that.

Only two things are actually different, and both live in 'SceneFactoryAssy':

  * a scene rejects the ``how:`` section of a ``connect:``. A scene states an
    end state, not the steps that reach it (see 'partcad.scene').
  * a scene's source file is checked against the scene-simplified ASSY schema,
    which is the same schema without ``how`` (see 'partcad_utils.assy_lint').
"""

from . import logging as pc_logging
from . import telemetry
from .assembly_connect import ConnectHow
from .assembly_factory_alias import AssemblyFactoryAlias
from .assembly_factory_assy import AssemblyFactoryAssy
from .assembly_factory_enrich import AssemblyFactoryEnrich
from .scene import Scene


class SceneFactoryMixin:
    """What makes an assembly factory produce a scene instead.

    Mixed in ahead of the assembly factory so these win over its own values;
    everything else about the factory is inherited unchanged.
    """

    OBJECT_KIND = "scene"
    OBJECT_CLASS = Scene
    STATS_DECLARED = "stats_scenes"
    STATS_INSTANTIATED = "stats_scenes_instantiated"

    def get_source_object(self, name, params=None):
        """A scene alias points at a scene, not at an assembly of the same name."""
        return self.ctx._get_scene(name, params)


@telemetry.instrument()
class SceneFactoryAssy(SceneFactoryMixin, AssemblyFactoryAssy):
    """The 'assy' scene type: an ASSY file used directly as a scene.

    The package points at the file and nothing else is declared: there is no
    assembly object in between for a scene to wrap, which is what makes a
    ``.assy`` in a ``scenes:`` section a scene and the same file in an
    ``assemblies:`` section an assembly.
    """

    def connect_how(self, node, connect, name):
        """A scene has no assembly instructions, and says so rather than ignoring them.

        Reported per link and the rest of the file is still read: the placement
        a ``connect:`` describes is perfectly good, and it is only the account
        of how the two objects were brought together that does not belong in a
        scene. The declaration is a mistake somebody can correct, hence an
        error rather than a warning -- the same finding the scene-simplified
        ASSY schema reports in the editor.
        """
        if isinstance(connect, dict) and connect.get("how") is not None:
            pc_logging.error(
                "%s: the scene '%s' connects '%s' with a 'how' section; a scene states where things are, "
                "not how they got there, so it is ignored"
                % (self.project.name, self.name, name or connect.get("name") or "<unnamed>")
            )
        return ConnectHow(None, where="%s: connect %s" % (self.name, name))


@telemetry.instrument()
class SceneFactoryAlias(SceneFactoryMixin, AssemblyFactoryAlias):
    pass


@telemetry.instrument()
class SceneFactoryEnrich(SceneFactoryMixin, AssemblyFactoryEnrich):
    pass
