## Context

This document is written for an implementer picking the work up cold. It records what was found, the trade-off
that decides the design, and which claims are measurements rather than estimates.

### The hot path

`Shape.get_wrapped()` (`shape.py:208-270`) is the single entry point for "give me this shape's geometry". On a
cache hit it does, in order:

1. `ctx.cache_shapes.read_async(cache_hash, keys)` (`shape.py:219`), which calls `hash.get()`
   (`cache_shape.py:83`) — and `CacheHash.get()` (`cache_hash.py:141-151`) first walks `self.dependencies`,
   reading and MD5-ing **every byte** of each one (`cache_hash.py:127-128`).
2. Reads the cached files (`cache.py:90-99`).
3. Deserializes: `.decode("utf-8")` → `json.loads` → the envelope dict (`cache_shape.py:110` via
   `shape_envelope.loads`).

Step 1 is the expensive one, and it is unavoidable in the current design: the hash *is* the cache key, so
nothing can be looked up until every dependency has been read.

`hash.get()` is guarded by `is_used` (`cache_hash.py:142`), so the dependency read happens once per `Shape`
object per process — not once per lookup. The cost is therefore per shape per run, which is exactly the
incremental-build floor this change is about.

### What `cache_dependencies_ignore` actually does

Do not mistake this for a hashing switch. `Shape.get_cache_dependencies_broken()` (`shape.py:167-170`) uses it
to decide whether a *broken* dependency disables caching for that shape. Dependencies are hashed either way,
via `set_dependencies()` at `shape.py:142`. The user-level knob is at
`partcad-utils/src/partcad_utils/user_config.py:386` and is threaded into child configs at
`assembly_factory_assy.py:195`. A new knob is needed for hashing mode; this one cannot be reused.

### Measured serialization overhead

On the analysis machine, an 8 MB payload: `hashlib.md5` 14 ms, `base64.b64encode` 30 ms, `json.dumps` 35 ms,
`json.loads` 14 ms, `.encode("utf-8")` 10 ms; on-disk size 1.33× the raw payload. These are real numbers from a
throwaway script, not estimates. The MD5 figure is for data already in memory — the file read that precedes it
is the larger cost for a model that is not in the page cache.

## Goals / Non-Goals

**Goals**

- A cache hit's cost is proportional to metadata consulted, not to the size of the source model.
- A cached payload is not re-encoded on its way to or from disk.
- Cache entries remain **content-addressed**, so an entry produced on one machine is still valid on another.
- Existing entries are never misread under new rules.

**Non-Goals**

- Changing what is cached, or the size-threshold policy.
- Changing BREP compression (`wrappers/ocp_serialize.py:186-191`).
- The sibling proposals' territory: sandbox concurrency, sandbox invocation count.

## Decisions

### D1 — Memoize the content digest; do not replace it

The obvious move is to key a dependency on `(size, mtime_ns)` instead of its content. **Do not do that as the
default.** It breaks a property the current design quietly has: because the key is a content hash, an entry
produced on one machine is valid on any other. A CI job that restores a warm cache directory, or a team sharing
one, gets hits today and would stop getting them if the key embedded local mtimes. That is a real regression
traded for a real speedup, and it is the wrong side of the trade.

Instead, keep the digest a **content** digest and make computing it cheap:

- Maintain a small local index in `user_config.internal_state_dir` mapping
  `(absolute path, size, mtime_ns, inode)` → content digest.
- `add_filename()` stats the file; on an index hit it uses the stored digest and never opens the file. On a
  miss it reads, hashes, and records.
- The cache key is unchanged in meaning: it is still the content digest. Cross-machine sharing keeps working;
  the index is a local accelerator that can be deleted at any time with no correctness consequence.

Hot-path cost: one `stat()` and one index lookup per dependency, against a full read and MD5 today.

**Offer metadata-only hashing as an opt-in**, for users who want the last stat's worth of speed and do not
share caches. `cache_hash.py:130`'s TODO points at this; make it a documented user-config option with the
trade-off written down, not the silent default.

### D2 — Hash dependencies concurrently, preserving digest order

`cache_hash.py:143` already asks for this. The constraint is that the digest depends on the order in which
dependencies contribute. Compute each file's digest independently (on `threadpool_manager`), then fold the
per-file digests into the running hasher in the original list order. With D1 in place this matters mainly for
the cold path, where files must actually be read.

### D3 — Store the payload raw

`Cache.write_data_async()` already writes one file per key (`cache.py:63`) and reads one file per key
(`cache.py:92`). So the change is confined to `ShapeCache`: split the envelope into

- a small JSON metadata file (name, label, location, assembly structure), and
- the payload as raw bytes in its own file,

instead of `shape_envelope.dumps(value).encode("utf-8")` (`cache_shape.py:44`). A write becomes one `write()`
of bytes already in hand; a read becomes one `read()` with no `json.loads` over a multi-megabyte string.

Two things to get right:

- **Assemblies are trees.** `Shape.get_cache_value()` is overridden by `Assembly` to store a nested structure
  (`shape.py:303-317` documents why: a flat compound would lose names, labels and sub-assemblies). The split
  must handle a tree with many payloads, not just one. Either store one payload file per leaf, or keep the tree
  in the metadata file with payload references.
- **The `"cmps"` key.** `get_wrapped()` caches components under `"cmps"` alongside the shape
  (`shape.py:218`, `shape.py:259-260`), and components can be nested lists (`shape.py:297-301`). Same treatment.

Whether the base64 layer can be dropped entirely — storing the zstd-compressed BREP bytes directly — depends on
nothing but the cache's own format, since the cache is not the wire. Dropping it saves the 1.33× inflation and
the encode/decode. Do it if the split lands cleanly; it is the whole point of storing raw bytes.

### D4 — Bump `cache_hash.VERSION`

`VERSION` (`cache_hash.py:24`) is mixed into every hash precisely so a change in what the bytes mean moves every
entry to a new key rather than letting an old entry be read under new rules. D1 does not change the digest's
meaning, but D3 changes the stored format. Bump it, and extend the comment block at `cache_hash.py:16-23` with
the reason, following the existing style. Old files are not deleted; they simply stop being looked up.

### D5 — Replace the `total_size()` calls

`cache_shape.py:56` and `cache_shape.py:61` walk the object graph to get a size that is already available as
`len(serialized_items[key])`. `read_async()` already does it that way (`cache_shape.py:121`). One-line change;
do it first, on its own commit, so it is trivially reviewable.

Note the two calls are not quite equivalent: `total_size(value)` measures the in-memory object, while
`len(serialized)` measures the encoded form. The thresholds they feed
(`cacheMemoryMaxEntrySize`, `cacheMemoryDoubleCacheMaxEntrySize`) are documented in terms of cache entries, and
`read_async` already compares against the encoded length — so the encoded length is the consistent choice.
Confirm the user-facing documentation of those settings matches before changing the semantics.

## Risks

| Risk | Mitigation |
|---|---|
| Serving a stale cache entry — the one failure that produces *wrong output* rather than a slow run | D1 keeps a content digest, so staleness requires the index to be wrong, not the key. Include inode and size, not just mtime; verify behavior across a `git checkout` that rewrites a file |
| Losing cross-machine cache validity | D1 is chosen specifically to preserve it; task 4.4 tests it explicitly |
| The metadata-only opt-in gets enabled by default later without the trade-off being re-read | Document it in the user config docs with the caveat inline, not just in this proposal |
| Assembly trees or `"cmps"` lists mishandled by the payload split | Tasks 3.4-3.6; `partcad/tests/unit/test_assembly_serialize.py` is the closest existing coverage |
| Existing digest tests break | Expected: `partcad/tests/unit/test_cache_hash.py` asserts exact digests and pins `VERSION` into them. Update them deliberately, do not loosen them |

## How to measure

Two distinct numbers; report both.

**Cache-hit floor.** Build a package once to warm the cache, then time a second, fully-cached run:

```bash
poetry run pc --no-ansi render <package>     # warm
time poetry run pc --no-ansi render <package>  # measure this one
```

Use a package with a large file-backed part — `examples/produce_part_step` with a deliberately large STEP file
is the clearest case. Drop the OS page cache between runs where the platform allows it, and say whether you
did: a warm page cache hides most of the read cost and makes the "before" number look better than it is.

**Per-payload overhead.** Instrument `ShapeCache.write_async`/`read_async` with timers around the
serialize/deserialize steps and report total time and total bytes written for a full package build.

**Expected direction.** The cache-hit floor should drop by roughly the time it takes to read and MD5 every
dependency file — which is why the large-part case is the one to measure. Payload overhead should drop by the
`json.dumps` + `encode` + `json.loads` time and, if base64 goes, by 1.33× on bytes written.

## Related, out of scope

`Shape.matches()` (`shape.py:151-165`) reads whole files for `pc search`. Same class of problem, different
command, no cache involved. Not part of this change; worth a separate issue.

## Open questions for the implementer

1. Should the digest index live per-user (`internal_state_dir`) or per-project? Per-user shares work across
   projects that reference the same vendored files; per-project is easier to reason about and to discard.
2. Should the index be a single file (read once per process) or a directory of small entries? A single file
   needs concurrency handling across the daemon and concurrent `pc` runs.
3. Is there a case where a dependency file is *expected* to change without its mtime changing — a generated
   file written by a tool that preserves timestamps? If so, D1's index needs a way to opt a path out.
4. Should `add_filename()`'s `FileNotFoundError` path (`cache_hash.py:132-135`, silently skipping a file that is
   "not yet downloaded") also participate in the index, or stay a plain miss? It currently makes a
   not-yet-downloaded dependency contribute nothing to the hash, which is worth a second look on its own.
