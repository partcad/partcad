@cli
Feature: `pc version` command
  As a user
  I want to run the version command
  So that I can see the PartCAD and PartCAD CLI versions

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-version @success
  Scenario: Show version information
    When I run "partcad version"
    Then STDOUT should contain "INFO:  PartCAD Python Module version: 0.7.32"
    And STDOUT should contain "INFO:  PartCAD CLI version: 0.7.32"
    # TODO: @alexanderilyin Make version run under "0.5" seconds
    And command takes less than "3" seconds
    And the command should exit with a status code of "0"
    And CLI version matches package version

  # @pc-version @offline
  # Scenario: Show version information while offline
  #   Given network connectivity is disabled
  #   When I run "partcad version"
  #   Then the command should succeed
  #   And STDERR should contain local version information

  # @pc-version @validation
  # Scenario: Verify version format
  #   When I run "partcad version"
  #   Then STDERR should match version pattern "v\d+\.\d+\.\d+"