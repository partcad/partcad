from dataclasses import dataclass
from typing import Optional, Protocol, Dict, Type, Any, Generic, TypeVar

from partcad.factory import Factory
from partcad import logging


@dataclass(frozen=True)
class Format:
    type: str
    ext: str

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Format):
            return (self.type, self.ext) == (other.type, other.ext)
        if isinstance(other, str):
            return self.type == other
        return False

    def __hash__(self) -> int:
        return hash(self.type)


class FormatSource(Protocol):
    """Marker Protocol – classes that define Format fields."""


T = TypeVar("T", bound=Type[FormatSource])

class FormatGroup(Generic[T]):
    def __init__(self, *sources: T) -> None:
        self._formats: Dict[str, Format] = {}
        annotations: Dict[str, type] = {}
        for source in sources:
            for name in dir(source):
                if name.startswith("_"):
                    continue
                val = getattr(source, name)
                if isinstance(val, Format):
                    self._formats[name] = val
                    setattr(self, name, val)
                    annotations[name] = Format
        self.__annotations__ = annotations

    def as_dict(self) -> dict[str, str]:
        """Return {format.type: format.ext}"""
        return {f.type: f.ext for f in self._formats.values()}

    def types(self) -> list[str]:
        """All 'type' fields of stored Formats."""
        return [f.type for f in self._formats.values()]

    def formats(self) -> list[Format]:
        """Return all Format objects."""
        return list(self._formats.values())

    def get_format(self, fmt_type: str) -> Optional[Format]:
        """
        Return the single Format object whose 'type' equals fmt_type.
        Example: get_format("stl") -> Format(type="stl", ext="stl").
        """
        logging.info(f"{fmt_type=}")
        for fobj in self._formats.values():
            if fobj.type == fmt_type:
                logging.info(f"{fobj.type=}")
                return fobj
        return None

    def get_formats_by_ext(self, extension: str) -> list[Format]:
        """
        Return all Format objects that have 'ext' equal to extension.
        Example: get_formats_by_ext("stl") -> [Format("stl", "stl")]
        Example: get_formats_by_ext("py") -> [Format("cadquery", "py"), Format("build123d", "py")]
        """
        result = []
        for fobj in self._formats.values():
            if fobj.ext == extension:
                result.append(fobj)
        return result
      

class FormatsMetaBase:

    def __init__(self) -> None:
        self._formats: Dict[str, Format] = {}

        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            value = getattr(self, attr_name)
            if isinstance(value, FormatGroup):
                for name, fmt in value._formats.items():
                    if not hasattr(self, name):
                        setattr(self, name, fmt)
                        self._formats[name] = fmt

        self.__annotations__ = {k: Format for k in self._formats}

    def __getattr__(self, item: str) -> Format:
        logging.info(f"{self._formats.values()=}")
        logging.info(f"{self.__dict__=}")
        logging.info(f"{self.__annotations__=}")
        for fobj in self._formats.values():
            if fobj.type == item.lower():
                return fobj
        raise AttributeError(f"No format1111111 '{item}' found in {self.__class__.__name__}")

    def __dir__(self) -> list[str]:
        return list(super().__dir__()) + list(self._formats)

    def as_dict(self) -> dict[str, str]:
        return {f.type: f.ext for f in self._formats.values()}

    def types(self) -> list[str]:
        return list({f.type for f in self._formats.values()})

    def formats(self) -> list[Format]:
        return list(self._formats.values())

    def get_format(self, fmt_type: str) -> Optional[Format]:
        """
        Return the single Format object whose 'type' equals fmt_type.
        Example: get_format("stl") -> Format(type="stl", ext="stl").
        """
        for fobj in self._formats.values():
            if fobj.type == fmt_type:
                return fobj
        return None
    
    def get_formats_by_ext(self, extension: str) -> list[Format]:
        """
        Return all Format objects that have '.ext' == extension.
        """
        return [fmt for fmt in self._formats.values() if fmt.ext == extension]
