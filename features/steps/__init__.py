import os
import pkgutil
import importlib.util

__all__ = []
PATH = [os.path.dirname(__file__)]

for loader, module_name, _ in pkgutil.walk_packages(PATH):
    __all__.append(module_name)
    try:
        _spec = loader.find_spec(module_name)
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        globals()[module_name] = _module
    except (ImportError, SyntaxError) as e:
        raise ImportError(f"Failed to load module {module_name}") from e
