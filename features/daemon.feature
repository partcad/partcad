@cli
Feature: `pc daemon` commands

  The per-workspace daemon is what most `pc` commands actually run on, so these
  scenarios drive it the way a user does: start it, ask it about itself, change
  its configuration, reset its data, stop it.

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-daemon @success @skip-windows
  Scenario: Start the daemon and stop it again
    When I run "pc --no-ansi daemon start"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "$HOME/.partcad/workspaces" with path
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD daemon stopped"

  @pc-daemon @success @skip-windows
  Scenario: Starting a daemon twice reuses the running one
    When I run "pc --no-ansi daemon start"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi daemon start"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "$HOME/.partcad/workspaces" with path
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
    # One daemon served both requests, so a second stop finds nothing.
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "No PartCAD daemon was running"

  @pc-daemon @success @skip-windows
  Scenario: Stopping a daemon that is not running says so
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "No PartCAD daemon was running"

  @pc-daemon @pc-status @success @skip-windows
  Scenario: Report the daemon's own version and storage
    When I run "pc --no-ansi daemon status"
    Then the command should exit with a status code of "0"
    And STDERR should contain "PartCAD version:"
    And STDERR should contain "Internal data storage location: $HOME/.partcad" with path
    And STDERR should contain "Tar cache size:"
    And STDERR should contain "Git cache size:"
    And STDERR should contain "Sandbox environments size:"
    And STDERR should contain "Conda package cache size:"
    And STDERR should contain "Total internal data storage size:"
    And STDERR should contain "DONE: Status: global:"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"

  @pc-daemon @pc-status @success @skip-windows
  Scenario: Report the daemon's own configuration and environment
    # The daemon inherits the environment of whatever starts it, which here is
    # this command -- so the variables below are the daemon's own, and reading
    # them back proves the report is the daemon's rather than the client's.
    Given environment variable "PC_TAGS" is set to "daemon-side"
    And environment variable "PC_REMOTE_SANDBOX_TOKEN" is set to "s3cr3t-do-not-print"
    When I run "pc --no-ansi daemon status config"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Configuration file: $HOME/.partcad/config.yaml" with path
    And STDERR should contain "remote_sandbox_token: <set>"
    And STDERR should not contain "s3cr3t-do-not-print"
    And STDERR should contain "DONE: StatusConfig: global:"
    When I run "pc --no-ansi daemon status env"
    Then the command should exit with a status code of "0"
    And STDERR should contain "PC_TAGS=daemon-side"
    # Scrubbed in the daemon, so the value never reaches the wire.
    And STDERR should contain "PC_REMOTE_SANDBOX_TOKEN=<scrubbed>"
    And STDERR should not contain "s3cr3t-do-not-print"
    And STDERR should contain "DONE: StatusEnv: global:"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"

  @pc-daemon @pc-telemetry @success @skip-windows
  Scenario: Set the daemon's telemetry settings
    When I run "pc --no-ansi daemon set telemetry type none"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Telemetry collection disabled"
    When I run "pc --no-ansi daemon set telemetry env test"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Telemetry environment set to test"
    When I run "pc --no-ansi daemon set telemetry type sentry"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Telemetry collection enabled with Sentry"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"

  @pc-daemon @pc-reset @success @skip-windows
  Scenario: Reset the daemon's cached data
    When I run "pc --no-ansi daemon reset --cache-only"
    Then the command should exit with a status code of "0"
    And STDERR should contain "DONE: Reset: global:"
    When I run "pc --no-ansi daemon reset --repo-only"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi daemon reset"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"

  @pc-daemon @success @skip-windows
  Scenario: The daemon serves the commands that follow it
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    When I run "pc --no-ansi daemon start"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi list parts"
    Then the command should exit with a status code of "0"
    And STDERR should contain "PartCAD parts:"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD daemon stopped"

  @pc-daemon @success @skip-windows
  Scenario: A directory with no package is not remembered as having none
    # The daemon answers from the context it keeps, and that context must never
    # be a failed load: the errors explaining one are logged while it is built,
    # so a cached failure is one command that says why followed by any number
    # that quietly say nothing and exit zero.
    When I run "pc --no-ansi list packages ..."
    Then the command should exit with a non-zero status code
    And STDERR should contain "PartCAD configuration file is not found"
    When I run "pc --no-ansi list packages ..."
    Then the command should exit with a non-zero status code
    And STDERR should contain "PartCAD configuration file is not found"
    # And a package written after that is read, rather than denied for as long as
    # this daemon runs.
    Given a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      sketches:
        circle:
          type: basic
          circle: 1
      """
    When I run "pc --no-ansi list packages ..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Root Package"
    When I run "pc --no-ansi daemon stop"
    Then the command should exit with a status code of "0"
