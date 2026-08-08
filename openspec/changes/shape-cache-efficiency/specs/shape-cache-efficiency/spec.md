## ADDED Requirements

### Requirement: A cache hit does not read its dependencies' contents
Determining whether a shape's cached entry is still valid SHALL NOT require reading the contents of that
shape's dependency files, in the common case where those files are unchanged since they were last hashed.

#### Scenario: An unchanged package is built twice
- **WHEN** a package whose source files have not changed is built a second time
- **THEN** the contents of its dependency files are not read

#### Scenario: A dependency's content changes
- **WHEN** a dependency file's content changes
- **THEN** the shape's cached entry is invalidated and the shape is rebuilt

#### Scenario: A dependency is touched without being changed
- **WHEN** a dependency file's timestamp changes but its content does not
- **THEN** the shape's cached entry remains valid and is reused

### Requirement: Cache entries stay content-addressed
A cache entry's key SHALL be derived from the content of the shape's inputs, not from machine-local file
metadata, so that an entry produced on one machine remains valid on another.

#### Scenario: A warmed cache is moved between machines
- **WHEN** a cache directory warmed on one machine is used on another, where the same source files have
  different timestamps
- **THEN** the entries in it are still found and reused

#### Scenario: The local acceleration data is discarded
- **WHEN** any local index used to avoid re-reading file contents is deleted
- **THEN** results are unchanged, and only performance is affected

### Requirement: Cached payloads are stored without re-encoding
A cached geometry payload SHALL be written to and read from disk without being re-encoded into a text format on
the way. The bytes written SHALL NOT be materially larger than the payload they represent.

#### Scenario: A shape is written to the cache
- **WHEN** a shape's geometry is stored in the cache
- **THEN** its payload is written as bytes, without being embedded into a text document that must be escaped
  and re-parsed

#### Scenario: A shape is read from the cache
- **WHEN** a shape's geometry is read from the cache
- **THEN** its payload is read as bytes, without parsing a text document containing it

### Requirement: Cached structure survives the payload split
Storing payloads separately from metadata SHALL preserve everything the cache records today, including an
assembly's nested tree of names, labels and sub-assemblies, and a shape's cached components.

#### Scenario: An assembly is cached and restored
- **WHEN** an assembly with sub-assemblies is cached and then read back
- **THEN** its hierarchy, names and labels are identical to what was stored

#### Scenario: A shape with components is cached and restored
- **WHEN** a shape whose components were cached is read back
- **THEN** its components, including nested lists, are identical to what was stored

### Requirement: A cache format change never reinterprets old entries
When the meaning of the bytes behind a cache key changes, the cache format version SHALL be advanced so that
entries written under the previous format are never read back under the new rules.

#### Scenario: A cache written by a previous version is present
- **WHEN** a cache directory contains entries written before a format change
- **THEN** those entries are not read, and the affected shapes are rebuilt rather than misinterpreted

### Requirement: Entry size decisions use the size actually stored
The cache's size thresholds SHALL be applied to the size of the data being stored, consistently on the write
and read paths, and determining that size SHALL NOT require traversing an in-memory object graph.

#### Scenario: An entry is checked against the size thresholds
- **WHEN** the cache decides whether an entry is too large to keep in memory
- **THEN** it uses the length of the serialized data it already holds
