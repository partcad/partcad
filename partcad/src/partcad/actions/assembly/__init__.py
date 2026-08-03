# 'import_assy' is the 'pc import assembly' entry point. It reads STEP assemblies
# through a sandbox (wrappers/wrapper_import_assy.py), so it needs no CAD library
# in the core process and is safe to import here. It is still loaded lazily, on
# first access rather than at 'import partcad' time, to keep the import graph
# shallow. 'from ...assembly import import_assy_action' resolves through the
# module __getattr__ below.

__all__ = [
    "import_assy_action",
]


def __getattr__(name):
    if name == "import_assy_action":
        from .import_assy import import_assy_action

        return import_assy_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
