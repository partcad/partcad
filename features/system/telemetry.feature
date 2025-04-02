#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-04-02
#
# Licensed under Apache License, Version 2.0.
#

@cli
Feature: `pc system telemetry` and `pc system set telemetry` commands

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-system-telemetry @success
  Scenario: Show telemetry info
    When I run "partcad system telemetry info"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry ID:"
    And STDOUT should contain "Telemetry type: 'sentry'"
    And STDOUT should contain "Telemetry env:"

  @pc-system-telemetry @success
  Scenario: Set telemetry type
    When I run "partcad system set telemetry type none"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry collection disabled"
    When I run "partcad system telemetry info"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry type: 'none'"

  @pc-system-telemetry @success
  Scenario: Set telemetry type
    # Reset settings
    When I run "partcad system set telemetry type none"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry collection disabled"
    When I run "partcad system set telemetry env dev"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry environment set to dev"
    # Set new settings
    When I run "partcad system set telemetry type sentry"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry collection enabled with Sentry"
    When I run "partcad system set telemetry env test"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry environment set to test"
    When I run "partcad system telemetry info"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Telemetry type: 'sentry'"
    And STDOUT should contain "Telemetry env: 'test'"

  @pc-system-telemetry
  Scenario: Set telemetry type
    When I run "partcad system set telemetry sentryDsn invalid"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Sentry DSN set to invalid"
    When I run "partcad system telemetry info"
    Then the command should exit with a non-zero status code
    And STDOUT should not contain "Telemetry type: `none'"
