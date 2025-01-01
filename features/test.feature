@cli @pc-test
Feature: `pc test` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @wip
  Scenario: `pc test -s /pub/std/metric/m:m3`
    Given I have a valid PartCAD configuration
    When I execute "pc test -s /pub/std/metric/m:m3"
    Then the command should exit with code 0
    And the output should contain "Test completed successfully"
    And no errors should be reported

  @success
  Scenario: `Recursively test all imported packages`
    Given a file named "partcad.yaml" with content:
      """
      import:
        raspberrypi:
          desc: Raspberry Pi
          type: git
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    When I run "pc test -r"
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Git operations: 1"
    Then STDOUT should contain "DONE: Test: this:"

  @wip
  Scenario: Test with invalid configuration
    Given I have an invalid PartCAD configuration
    When I execute "pc test -s /pub/std/metric/m:m3"
    Then the command should exit with non-zero code
    And the output should contain "Configuration error"

  @wip
  Scenario: Test with non-existent part
    Given I have a valid PartCAD configuration
    When I execute "pc test -s /pub/non/existent/part"
    Then the command should exit with non-zero code
    And the output should contain "Part not found"
