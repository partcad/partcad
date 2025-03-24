#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import hashlib
import os
import struct

from . import logging as pc_logging


class CacheHash:
    def __init__(self, name: str, algo="md5", hasher=None, cache=False):
        self.name = name
        self.is_empty = True
        self.is_used = False
        if not cache:
            # Caching is disabled, no initialization needed
            self.hasher = None
            return

        if hasher != None:
            self.hasher = hasher.copy()
        else:
            if algo == "md5":
                self.hasher = hashlib.md5()
            elif algo == "sha1":
                self.hasher = hashlib.sha1()
            elif algo == "sha256":
                self.hasher = hashlib.sha256()
            else:
                raise ValueError(f"Unknown hash algorithm: {algo}")

        self.dependencies = []

    def touch(self):
        if self.is_used:
            pc_logging.warning(f"Hash update after being used: {self.name}")
        self.is_empty = False

    # TODO(clairbee): do not "add_" anything to the hash immediately.
    # Instead, add the data to a list and then add it to the hash when needed.

    def add_dict(self, data: dict):
        if not self.hasher:
            # Caching is disabled
            return
        if data is None or len(data.keys()) == 0:
            # Do not consider it not being empty
            return

        def recurse(val):
            if isinstance(val, dict):
                for k in sorted(val.keys()):
                    self.hasher.update(str(k).encode())
                    recurse(val[k])
            elif isinstance(val, str):
                self.hasher.update(val.encode())
            elif isinstance(val, (list, tuple, set)):
                for item in sorted(val) if not isinstance(val, list) else val:
                    recurse(item)
            else:
                self.hasher.update(str(val).encode())

        recurse(data)
        self.touch()

    def add_string(self, string: str):
        if not self.hasher:
            # Caching is disabled
            return
        if string is None:
            # Do not consider it not being empty
            return

        self.hasher.update(string.encode())
        self.touch()

    def add_bytes(self, bytes: bytes):
        if not self.hasher:
            # Caching is disabled
            return
        if bytes is None or len(bytes) == 0:
            # Do not consider it not being empty
            return

        self.hasher.update(bytes)
        self.touch()

    def add_filename(self, filename: str):
        if not self.hasher:
            # Caching is disabled
            return
        if filename is None:
            # Do not consider it not being empty
            return

        try:
            # Track changes to the file content
            with open(filename, "rb") as f:
                self.hasher.update(f.read())

            # TODO(clairbee): optionally, track changes by file modification time only
            # self.hasher.update(struct.pack("f", os.path.getmtime(filename)))
        except FileNotFoundError:
            # TODO(clairbee): trigger preload if content hashing is back
            # This happens for all files that are not yet downloaded
            return
        self.touch()

    def set_dependencies(self, dependencies: list[str]) -> None:
        self.dependencies = dependencies

    def get(self) -> str | None:
        if not self.is_used:
            # TODO(clairbee): make I/O asynchronous and parallel, but maintain the order of hashing
            for filename in self.dependencies:
                self.add_filename(filename)

        self.is_used = True
        if self.is_empty:
            return None

        return self.hasher.hexdigest()
