from typing import Callable, Dict

_factory_registry: Dict[str, Callable] = {}

def register_factory(format_type: str):
    def decorator(factory_cls: Callable):
        _factory_registry[format_type] = factory_cls
        return factory_cls
    return decorator

def get_factory(format_type: str) -> Callable | None:
    return _factory_registry.get(format_type)
