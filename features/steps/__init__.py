import os
import pkgutil

__all__ = []
PATH = [os.path.dirname(__file__)]

for loader, module_name, _ in pkgutil.walk_packages(PATH):
    __all__.append(module_name)
    try:
        _module = loader.find_module(module_name).load_module(module_name)
        globals()[module_name] = _module
    except Exception as e:
        raise ImportError(f"Failed to load module {module_name}: {e}")
