#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-08-09
#
# Licensed under Apache License, Version 2.0.
#


class NeedsUpdateException(Exception):
    pass


class EmptyShapesError(Exception):
    """Exception raised when no shapes are found for rendering."""

    def __init__(self, message="No shapes found to render. Please specify valid sketches, parts, or assemblies."):
        self.message = message
        super().__init__(self.message)


class AssemblyDocumentError(Exception):
    """Base exception for the documents generated from an assembly."""


class NotAnAssemblyFileError(AssemblyDocumentError):
    """Exception raised when an assembly is not one that can be documented.

    An assembly instruction book is built out of the steps an Assembly YAML
    (ASSY) file declares; an assembly that comes from anywhere else has none.
    """


class NotManufacturableError(AssemblyDocumentError):
    """Exception raised when an assembly is not meant to be built at all."""


class ObjectNameTakenError(Exception):
    """An object was created under a name its package already holds in use.

    A package holds one object per name, so an object being registered under a
    name that is taken means two declarations are claiming it - or that
    something is installing an object into a package that never asked for it.
    Overwriting the entry instead of saying so is how an 'enrich' came to
    replace the very object it enriches: the enriched clone used to be
    registered in the *source* package, under the enriching object's name, and
    a source package that happens to use that name for the original lost it
    (see 'PartFactoryEnrich.instantiate').

    Raised while the object is being created, like the factory exceptions in
    'partcad.factory', so 'Project.record_broken_object()' files it against the
    one object that could not be created and the rest of the package loads. The
    object already registered under that name is the one that stays.

    An object that deliberately takes the place of another - the enriched clone
    replacing the 'enrich' object standing in for it - is not this: the factory
    says so through 'Project.replacing_object()'.
    """

    def __init__(self, kind: str, package_name: str, name: str):
        self.kind = kind
        self.package_name = package_name
        self.name = name
        super().__init__("the package '%s' already has a %s named '%s'" % (package_name, kind, name))


class PartFactoryError(Exception):
    """Base exception for all part factory-related errors."""

    pass


class PartFactoryInitializationError(PartFactoryError):
    """Exception for errors during part factory initialization."""

    pass


class PartProcessingError(PartFactoryError):
    """Exception for errors during part processing."""

    pass


class FileReadError(PartProcessingError):
    """Exception for errors reading files."""

    pass


class ValidationError(PartFactoryError):
    """Exception for validation errors in part factory configuration."""

    pass


class PartIsEmptyOrFailed(PartFactoryError):
    """Exception for when a part is empty or failed to initialize."""

    pass
