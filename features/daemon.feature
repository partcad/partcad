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
    And STDERR should contain "Total internal data storage size:"
    And STDERR should contain "DONE: Status: global:"
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
