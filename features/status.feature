@cli
Feature: `pc system status` command

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      private: true
      pythonVersion: ">=\\d+\\.\\d+"
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      """

  @pc-init @pc-status @success
  Scenario: Show subsystems status
    When I run "partcad status"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: $HOME/.partcad" with path
    And STDOUT should match the regex "Tar cache size: \d\.\d+[KMGT]B"
    And STDOUT should match the regex "Git cache size: \d\.\d+[KMGT]B"
    And STDOUT should contain "Sandbox environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: global:"

  @wip
  Scenario: Show status with corrupted cache
    Given the cache directory is corrupted
    When I run "partcad status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Cache integrity check failed"

  @wip
  Scenario: Show status with insufficient permissions
    Given I have insufficient permissions for "$HOME/.partcad"
    When I run "partcad status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Permission denied"
