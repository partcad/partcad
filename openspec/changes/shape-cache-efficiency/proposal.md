## Why

The point of the shape cache is that an unchanged shape costs nearly nothing. Today it costs a full read and
hash of its source model, plus several full copies of its cached payload. That sets the floor on every
incremental run — the case users hit most often, and the one where the cache is supposed to be the whole story.

### 1. The cache cannot be consulted until every dependency has been read end to end

`CacheHash.get()` (`partcad/src/partcad/cache_hash.py:141`) walks `self.dependencies` and calls
`add_filename()` on each, which does:

```python
with open(filename, "rb") as f:
    self.hasher.update(f.read())
```

(`cache_hash.py:127-128`) — the **entire file**, read into memory and hashed. For a file-backed shape that file
*is* the source model: `PartFactoryFile.post_create()` appends `self.path` to `cache_dependencies`
(`part_factory_file.py:56`), as do `assembly_factory_file.py:39` and `sketch_factory_file.py:58`.
`PartFactoryPython` and `PartFactoryScad` add each declared `dependencies:` entry on top
(`part_factory_python.py:48`, `part_factory_scad.py:156`).

`Shape.get_wrapped()` needs that hash *before* it can look anything up (`shape.py:216-219`), so a cache hit on a
200 MB STEP part still pays a full read plus MD5 of it — serially, on the event loop. The code already carries
the TODOs: "optionally, track changes by file modification time only" (`cache_hash.py:130`) and "make I/O
asynchronous and parallel, but maintain the order of hashing" (`cache_hash.py:143`).

### 2. The payload is base64 inside JSON, re-encoded on every hop

A shape envelope's `"brep"` value is *already* a base64 string (`wrappers/ocp_serialize.py:265-266`, which
base64-encodes the zstd-compressed BREP). `ShapeCache.write_async()` then calls
`shape_envelope.dumps(value).encode("utf-8")` (`cache_shape.py:44`), so `json.dumps` re-scans and re-escapes
that entire string into a new one, and `.encode()` copies it again. Reads reverse all of it
(`cache_shape.py:110`). Each render then re-serializes the same payload once more (`shape.py:828`).

Measured on the analysis machine with an 8 MB payload: ~30 ms base64 + ~35 ms `json.dumps` + ~10 ms UTF-8
encode, at 1.33× on-disk inflation. Modest per shape; it multiplies by shape count and by format count.

### 3. A deep object-graph walk where a length is already in hand

`ShapeCache.write_async()` calls `total_size(value)` (`cache_shape.py:56` and `cache_shape.py:61`) — a
`gc.get_referents` breadth-first walk of the object graph (`partcad-utils/src/partcad_utils/utils.py:63`) —
purely to compare against the size thresholds. The serialized length is sitting in the same scope, in
`serialized_items[key]`. `read_async()` already does it the cheap way: `data_len = len(data)`
(`cache_shape.py:121`). This one is free to fix.

## What Changes

- **Hash dependencies by metadata, not content, by default.** Key a dependency's contribution on
  `(size, mtime_ns)`, falling back to content hashing when metadata is unavailable, and keep full content
  hashing available for callers that need it. Bump `cache_hash.VERSION` so no existing entry is ever read back
  under the new rules.
- **Hash dependencies concurrently**, as `cache_hash.py:143` already asks for, while preserving the order in
  which they contribute to the digest.
- **Store the BREP payload as raw bytes.** Write the payload to its own cache file and keep the JSON envelope
  for metadata only, so a cache write is one `write()` with no re-encode and a read is one `read()`.
- **Replace the two `total_size()` calls** in `ShapeCache.write_async()` with the serialized length already
  computed.

## Capabilities

### New Capabilities

- `shape-cache-efficiency`: The requirement that the cost of a cache hit is proportional to the metadata
  consulted rather than to the size of the source model or the cached payload; that dependency freshness is
  determined without reading file contents in the common case; and that a cached payload is not re-encoded on
  its way to or from disk.

## Impact

- **Modified**: `partcad/src/partcad/cache_hash.py` — `add_filename()`, `get()`, `set_dependencies()`, and
  `VERSION`.
- **Modified**: `partcad/src/partcad/cache_shape.py` — `write_async()`/`read_async()` payload handling and the
  size checks.
- **Modified (possibly)**: `partcad/src/partcad/cache.py` — `write_data_async`/`read_data_async` already write
  one file per key (`cache.py:63`, `cache.py:92`), so a raw-bytes payload may need no new file layout at all.
- **Modified**: `partcad/tests/unit/test_cache_hash.py` — the existing tests assert exact digests and will need
  updating alongside the `VERSION` bump.
- **New specs**: `openspec/specs/shape-cache-efficiency/spec.md`.
- **Unchanged**: the wire envelope between core and wrappers. This change is about what the *cache* stores and
  how freshness is decided, not about what crosses the sandbox boundary.

## Non-Goals

- Changing what is cached, or the cache's eviction and size-threshold policy
  (`cacheFilesMinEntrySize`, `cacheMemoryMaxEntrySize`, `cacheMemoryDoubleCacheMaxEntrySize`).
- Overlapping sandbox operations (sibling proposal: `sandbox-run-concurrency`).
- Reducing the number of sandbox invocations (sibling proposal: `sandbox-process-reuse`).
- Changing the compression of BREP payloads. zstd at level 3 is already a considered choice
  (`wrappers/ocp_serialize.py:186-191`).
