@wip @cli @add-assembly
Feature: `pc info` command

  Background: Initialize Public PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
        pub:
          type: git
          url: https://github.com/openvmp/partcad-index.git
      parts:
      assemblies:
      """

  @pc-info
  Scenario: Show part details
    When I run "partcad info /pub/std/metric/cqwarehouse:fastener/hexhead-din931"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "'name': 'fastener/hexhead-din931',"
    And STDOUT should contain "'orig_name': 'fastener/hexhead-din931',"

  @pc-info
  Scenario: Show simplified part information
    When I run "partcad info -s /pub/std/metric/m:m3"
    Then the command should exit with a status code of "0"
    And STDOUT should contain only essential fields
    And STDOUT should not contain detailed specifications

  @pc-info
  Scenario: Show interactive part information
    When I run "partcad info -i /pub/std/metric/m:m3-screw"
    Then the command should exit with a status code of "0"
    And an interactive viewer should be launched
    And the viewer should display the part model
