from . import add, assembly, package, part, scene, shape, sketch

__all__ = [
    "add",
    "part",
    "shape",
    "sketch",
    "package",
    "assembly",
    "scene",
    "filter_object_action",
]


def __getattr__(name):
    # 'pc filter' is one action over both kinds it applies to - an assembly and
    # a scene are the same document read for two purposes, and filtering one is
    # filtering the other - so it sits here rather than under either. Lazily,
    # like every other action: it pulls in 'ruamel.yaml' and the lint checker.
    if name == "filter_object_action":
        from .filter import filter_object_action

        return filter_object_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
