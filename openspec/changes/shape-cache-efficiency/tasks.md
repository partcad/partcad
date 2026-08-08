## 1. Confirm the finding and establish the baseline

- [ ] 1.1 Bring up the dev container (root `AGENTS.md`, "Where commands run") — everything below runs inside it
- [ ] 1.2 Read `cache_hash.py` in full, `cache.py` in full, `cache_shape.py` in full, and `Shape.get_wrapped()`
      (`shape.py:208-270`)
- [ ] 1.3 Confirm the cache-hit path reads dependency files end to end: instrument `CacheHash.add_filename()`
      (`cache_hash.py:117`) to log bytes read, then run a fully-cached build and check the total against the
      sum of the source model sizes
- [ ] 1.4 Confirm `hash.get()`'s `is_used` guard (`cache_hash.py:142`) means this is paid once per shape per
      run, not once per lookup — so the cost scales with shape count, not access count
- [ ] 1.5 Time a fully-cached run with and without the OS page cache dropped, on a package with a large
      file-backed part. Record both, and record which is which
- [ ] 1.6 Instrument `ShapeCache.write_async`/`read_async` to report serialize/deserialize time and bytes
      written for a full build
- [ ] 1.7 Paste both baselines into the PR description before writing implementation code

## 2. The free win first (separate commit)

- [ ] 2.1 Replace `total_size(value)` at `cache_shape.py:56` and `cache_shape.py:61` with
      `len(serialized_items[key])`, matching what `read_async` already does at `cache_shape.py:121`
- [ ] 2.2 Confirm the semantic shift is the right one: the thresholds
      (`cacheMemoryMaxEntrySize`, `cacheMemoryDoubleCacheMaxEntrySize`) should compare against the encoded
      length, as `read_async` does. Check the user-facing documentation of those settings agrees
- [ ] 2.3 Handle the `not user_config.cache` branch, where `serialized_items` was never built — it currently
      falls through to `total_size` at line 61 and still needs a size
- [ ] 2.4 Confirm `total_size` has no remaining hot-path callers that matter; note that
      `Shape.shape_info()` (`shape.py:550`) still uses it, which is fine — it is a diagnostic command
- [ ] 2.5 Commit this on its own so it is trivially reviewable

## 3. Cheap dependency freshness

- [ ] 3.1 Read `design.md` D1 in full before writing code. The decision to keep a **content** digest and
      memoize it — rather than switching the key to `(size, mtime)` — is the load-bearing one, and reversing it
      silently breaks cross-machine cache validity
- [ ] 3.2 Implement the digest index: `(absolute path, size, mtime_ns, inode)` → content digest, stored under
      `user_config.internal_state_dir`
- [ ] 3.3 Rework `add_filename()` (`cache_hash.py:117`) to stat first and consult the index; read and hash only
      on a miss, recording the result
- [ ] 3.4 Make the index safe to delete at any time, and prove it: deleting it must change performance only,
      never results
- [ ] 3.5 Decide and document the index's scope and file layout (`design.md`, open questions 1 and 2), including
      concurrent access from the daemon and from parallel `pc` runs
- [ ] 3.6 Add the opt-in metadata-only hashing mode as a documented user-config setting, with its trade-off
      stated inline in the docs. It must not be the default
- [ ] 3.7 Implement concurrent dependency hashing (`design.md` D2), folding per-file digests into the hasher in
      the original list order. Add a test that reordering the input list changes the digest, so the ordering
      guarantee is pinned

## 4. Raw payload storage

- [ ] 4.1 Split `ShapeCache` storage into a small JSON metadata file plus raw payload bytes, replacing
      `shape_envelope.dumps(value).encode("utf-8")` at `cache_shape.py:44`
- [ ] 4.2 Drop the base64 layer for the cache if the split lands cleanly — the cache is not the wire, so it can
      store the zstd-compressed BREP bytes directly. This is where the 1.33× and the encode/decode time go
- [ ] 4.3 Bump `cache_hash.VERSION` (`cache_hash.py:24`) and extend the comment block at `cache_hash.py:16-23`
      with the reason, in the existing style
- [ ] 4.4 Verify an entry written on one machine is readable on another — copy a warmed cache directory to a
      different machine (or a container with different mtimes) and confirm hits. This is the property D1 exists
      to protect
- [ ] 4.5 Handle assembly trees: `Assembly` overrides `get_cache_value()` to store a nested structure
      (`shape.py:303-317`). Either one payload file per leaf, or payload references inside the metadata file
- [ ] 4.6 Handle the `"cmps"` key and its nested component lists (`shape.py:218`, `shape.py:259-260`,
      `shape.py:297-301`)
- [ ] 4.7 Confirm a cache file written by the previous format is never read under the new rules — it should miss
      cleanly on the bumped `VERSION`, not raise

## 5. Tests

- [ ] 5.1 Update `partcad/tests/unit/test_cache_hash.py` — it asserts exact digests and pins `VERSION` into
      them. Update deliberately; do not loosen the assertions to make them pass
- [ ] 5.2 Add: modifying a dependency's content invalidates the entry, whether or not the index has an entry for
      the old version
- [ ] 5.3 Add: touching a file without changing its content produces the **same** digest (the index misses, the
      content hash is recomputed, the key is unchanged) — this is the property that keeps cache hits after a
      fresh `git clone`
- [ ] 5.4 Add: a fully-cached build reads no dependency file content (assert via an instrumented `open`, or by
      making the file unreadable after the first build)
- [ ] 5.5 Round-trip tests for the new payload storage: plain shape, assembly tree, components, and an entry
      large enough to exercise the size thresholds
- [ ] 5.6 Check `partcad/tests/unit/test_assembly_serialize.py` still passes and extend it if the assembly tree
      layout changed

## 6. Validate

- [ ] 6.1 `poetry run pytest partcad partcad-cli -x -p no:error-for-skips -p no:warnings --dist no`
- [ ] 6.2 `poetry run behave`
- [ ] 6.3 Re-run both baseline measurements from task 1 and record the after numbers next to them, stating
      whether the page cache was dropped
- [ ] 6.4 Confirm geometry is unchanged: rendered outputs from a cached build match those from a cold build
- [ ] 6.5 Confirm on-disk cache size before and after

## 7. Land it

- [ ] 7.1 Remove the instrumentation added in task 1
- [ ] 7.2 Document the new user-config setting wherever the other cache settings are documented
- [ ] 7.3 Move the delta spec into `openspec/specs/shape-cache-efficiency/spec.md`
- [ ] 7.4 Run `pre-commit run --config dev-tools/pre-commit-config.yaml` inside the container and re-stage
      anything the formatting hooks rewrote
- [ ] 7.5 Commit inside the container; verify with `git log -1 --stat`
