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
