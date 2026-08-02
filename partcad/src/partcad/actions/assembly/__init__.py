# 'import_assy' is the in-process STEP-CAF assembly reader; it needs OCCT, which
# is optional (the 'cad' extra). It is loaded lazily on first access - not at
# 'import partcad' time - so OCP stays off the import path, and a missing CAD
# library surfaces as a clear "install partcad[cad]" error rather than an opaque
# ImportError. 'from ...assembly import import_assy_action' resolves through the
# module __getattr__ below.

__all__ = [
    "import_assy_action",
]


def __getattr__(name):
    if name == "import_assy_action":
        try:
            from .import_assy import import_assy_action
        except ImportError as e:
            raise ImportError(
                "Importing a STEP/BREP assembly ('pc import assembly') needs the CAD "
                "libraries, which are optional. Install them with 'pip install partcad[cad]'."
            ) from e
        return import_assy_action
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
