# 'import_assy' is the 'pc import assembly' entry point and 'convert' is the
# 'pc convert assembly' one. Both read their input through a sandbox
# (wrappers/wrapper_import_assy.py, wrappers/wrapper_import_urdf.py), so neither
# needs a CAD library in the core process and both are safe to import here. They
# are still loaded lazily, on first access rather than at 'import partcad' time,
# to keep the import graph shallow. 'from ...assembly import import_assy_action'
# resolves through the module __getattr__ below.

__all__ = [
    "convert_assembly_action",
    "import_assy_action",
]


def __getattr__(name):
    if name == "import_assy_action":
        from .import_assy import import_assy_action

        return import_assy_action
    if name == "convert_assembly_action":
        from .convert import convert_assembly_action

        return convert_assembly_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
