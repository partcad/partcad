# 'import_world' is the 'pc import scene' entry point and 'convert' is the
# 'pc convert scene' one. Both read their input through a sandbox
# (wrappers/wrapper_import_world.py), so neither needs a CAD library in the core
# process and both are safe to import here. They are still loaded lazily, on
# first access rather than at 'import partcad' time, to keep the import graph
# shallow. 'from ...scene import import_world_action' resolves through the
# module __getattr__ below.

__all__ = [
    "convert_scene_action",
    "import_scene_action",
    "import_world_action",
]


def __getattr__(name):
    if name == "import_world_action":
        from .import_world import import_world_action

        return import_world_action
    if name == "import_scene_action":
        from .import_world import import_scene_action

        return import_scene_action
    if name == "convert_scene_action":
        from .convert import convert_scene_action

        return convert_scene_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
