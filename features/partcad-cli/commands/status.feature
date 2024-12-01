@cli
Feature: `pc status` command

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
      parts:
      assemblies:
      """

  @pc-init @pc-status @success
  Scenario: Show subsystems status
    When I run "partcad status"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: $HOME/.partcad"
    And STDOUT should match "Tar cache size: \d+(\.\d+)? [KMGT]B"
    And STDOUT should match "Git cache size: \d+(\.\d+)? [KMGT]B"
    And STDOUT should contain "Runtime environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: this:"

  Scenario: Show status with corrupted cache
    Given the cache directory is corrupted
    When I run "partcad status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Cache integrity check failed"

  Scenario: Show status with insufficient permissions
    Given I have insufficient permissions for "$HOME/.partcad"
    When I run "partcad status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Permission denied"
