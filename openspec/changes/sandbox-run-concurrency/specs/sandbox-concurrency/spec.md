## ADDED Requirements

### Requirement: Independent sandbox operations execute concurrently
Sandboxed CAD operations that do not mutate the same environment SHALL be able to execute concurrently, up to a
configured concurrency bound. No single lock SHALL serialize every sandbox execution in a process.

#### Scenario: Several parts are instantiated at once
- **WHEN** a package containing several independent parts is built on a machine with more than one core
- **THEN** more than one sandbox process is in flight at the same time, up to the configured bound

#### Scenario: Several formats are rendered from one shape
- **WHEN** rendering work is gathered onto a single event loop, as `Project.render_async` does
- **THEN** those render operations execute concurrently rather than one at a time

### Requirement: Mutual exclusion is scoped to the environment being mutated
Mutual exclusion between sandbox operations SHALL be keyed on the environment being mutated — a sandbox path or
a v-env path — and not on the runtime object. An operation that installs nothing SHALL NOT exclude an
unrelated operation that installs nothing.

#### Scenario: A sessionless run overlaps another sessionless run
- **WHEN** two sandbox operations run in environments whose dependencies are already provisioned
- **THEN** neither operation waits for the other

#### Scenario: An install excludes runs in the same environment
- **WHEN** a package is being installed into an environment
- **THEN** no sandbox process executes in that environment until the install has completed

### Requirement: Waiting for a sandbox lock does not block an event loop
Acquiring the right to execute a sandbox operation SHALL NOT block the thread running an event loop. A
sandbox operation that is waiting SHALL leave its event loop free to make progress on other work.

#### Scenario: Unrelated async work proceeds while a sandbox operation waits
- **WHEN** a sandbox operation is waiting for another operation to release an environment
- **THEN** other coroutines scheduled on the same event loop, such as cache file I/O, continue to run

### Requirement: Concurrency is explicitly bounded
The number of sandbox processes running simultaneously SHALL be bounded by an explicit limit derived from the
user's thread configuration, so that lifting serialization does not permit unbounded process fan-out.

#### Scenario: A package declares more shapes than the bound
- **WHEN** more sandbox operations are requested at once than the configured bound allows
- **THEN** the excess operations queue, and the number in flight never exceeds the bound

### Requirement: Concurrent execution preserves environment integrity
Concurrent sandbox execution SHALL NOT permit a package install to replace files in an environment while a
sandbox process is executing in that environment. In particular, installing a distribution that overwrites the
OCP native module SHALL NOT be able to interleave with another operation's use of that module.

#### Scenario: A CadQuery part and a build123d part are built together
- **WHEN** two parts sharing one session v-env, one requiring CadQuery and one requiring build123d, are built
  concurrently from a freshly provisioned sandbox
- **THEN** both parts instantiate successfully, and neither sandbox process terminates abnormally with no
  output — the signature of two incompatible OCP builds loaded into one process
