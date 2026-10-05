## ADDED Requirements

### Requirement: A shape's exports share one sandbox invocation
Exporting a shape to several formats SHALL require one sandbox invocation, not one per format. The shape's
geometry SHALL be decoded once per export request regardless of how many formats it produces.

#### Scenario: One shape is rendered to several formats
- **WHEN** a shape is rendered to more than one format in a single request
- **THEN** exactly one sandbox process is started for that shape's exports

#### Scenario: One exporter fails among several
- **WHEN** one requested format fails to export and the others succeed
- **THEN** the successful outputs are written, and the failure is reported for that format alone rather than
  aborting the remaining formats

### Requirement: Transformations do not require dedicated sandbox invocations
Applying a shape's configured `offset` or `scale` SHALL NOT require a sandbox invocation separate from the one
that produced the shape, where a producing invocation exists.

#### Scenario: A part declares both an offset and a scale
- **WHEN** a part configured with both `offset` and `scale` is instantiated
- **THEN** no additional sandbox process is started to apply either transformation

#### Scenario: A transformed shape is served from the cache
- **WHEN** a shape carrying a transformation is served from the cache, so no producing invocation runs
- **THEN** the transformation is still applied correctly

#### Scenario: A transformation changes
- **WHEN** a shape's `offset` or `scale` configuration changes
- **THEN** its cached entry is invalidated, and the newly configured transformation is reflected in the result

### Requirement: Sandbox interpreters may be reused across operations
The system SHALL support serving more than one operation from a single sandbox interpreter, so that the cost of
starting the interpreter and importing the CAD stack is amortized rather than paid per operation.

#### Scenario: Several operations run in one environment
- **WHEN** several sandbox operations are requested against the same provisioned environment
- **THEN** they may be served by the same interpreter without it being restarted between them

#### Scenario: No daemon is running
- **WHEN** an operation runs without the background daemon
- **THEN** it still completes correctly, with any reuse scoped to the lifetime of the process that requested it

### Requirement: A reused interpreter does not observe another operation's state
An interpreter serving more than one operation SHALL produce, for any given request, the same result it would
produce as the first request that interpreter served.

#### Scenario: The same request is repeated on a warm interpreter
- **WHEN** a request is served by an interpreter that has already served other, unrelated requests
- **THEN** its output is identical to the output of the same request served by a freshly started interpreter

### Requirement: A reused interpreter is retired when its environment changes
An interpreter SHALL NOT continue serving requests after the environment it was started in has been modified by
a package install, so that it can never execute against files that have since been replaced on disk.

#### Scenario: A package is installed into an environment with a live interpreter
- **WHEN** a package is installed into a sandbox or v-env that a reused interpreter was started in
- **THEN** that interpreter is retired, and subsequent operations are served by an interpreter started after the
  install

### Requirement: An interpreter crash does not silently lose an operation
If a reused interpreter terminates unexpectedly, the system SHALL restart it and retry the interrupted
operation once. A second failure SHALL be reported as an error rather than retried indefinitely or ignored.

#### Scenario: An interpreter dies mid-request
- **WHEN** an interpreter serving a request terminates abnormally
- **THEN** the request is retried once on a fresh interpreter, and a repeated failure is surfaced to the caller

### Requirement: The core process still holds no live geometry
Reusing interpreters SHALL NOT change where geometry lives: the core process SHALL continue to carry shapes as
opaque BREP envelopes and SHALL NOT import the OCP library.

#### Scenario: A full render completes in the core process
- **WHEN** a package is rendered from a process that imported PartCAD
- **THEN** the OCP library is never imported into that process
