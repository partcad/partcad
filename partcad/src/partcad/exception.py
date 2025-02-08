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
