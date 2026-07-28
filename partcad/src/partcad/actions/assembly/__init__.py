# 'import_assy' is the in-process STEP-CAF assembly reader and imports OCP at
# module scope. It is loaded lazily on first access - not at 'import partcad'
# time - so OCP stays off the import path. 'from ...assembly import
# import_assy_action' still resolves through the module __getattr__ below.

__all__ = [
    "import_assy_action",
]


def __getattr__(name):
    if name == "import_assy_action":
        from .import_assy import import_assy_action

        return import_assy_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
