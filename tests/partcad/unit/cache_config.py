#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The cache-related slice of a user configuration, for tests to drive directly.

The real 'partcad_utils.UserConfig' reads files and the environment, and a test
that wants one cache tier pointed at a temporary directory should not have to
arrange either. This carries the same attribute names the cache reads, with the
limits opened up so that a test's few-byte payloads are not filtered out by a
size window meant for real geometry.
"""


class CacheUserConfig:
    """A stand-in user config with every cache tier off except the ones asked for."""

    def __init__(self, internal_state_dir, **overrides):
        self.internal_state_dir = str(internal_state_dir)

        # Memory
        self.cache_memory = True
        self.cache_memory_max_entry_size = 0
        self.cache_memory_double_cache_max_entry_size = 0

        # Files
        self.cache = True
        self.cache_min_entry_size = 0
        self.cache_max_entry_size = 0

        # Remote (memcached)
        self.cache_remote = False
        self.cache_remote_server = ""
        self.cache_remote_namespace = "partcad-test"
        self.cache_remote_expiration = 0
        self.cache_remote_min_entry_size = 0
        self.cache_remote_max_entry_size = 0

        # S3
        self.cache_s3 = False
        self.cache_s3_bucket = ""
        self.cache_s3_prefix = "partcad/"
        self.cache_s3_region = "us-east-1"
        self.cache_s3_endpoint_url = ""
        self.cache_s3_min_entry_size = 0
        self.cache_s3_max_entry_size = 0

        for key, value in overrides.items():
            if not hasattr(self, key):
                raise AttributeError("no such cache option: %s" % key)
            setattr(self, key, value)
