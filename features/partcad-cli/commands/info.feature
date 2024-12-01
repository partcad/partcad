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

# pc info -s /pub/std/metric/m:m3
# pc info -i /pub/std/metric/m:m3-screw
# TODO: @alexanderilyin: Add scenario for 'pc info -i ...'
# TODO: @alexanderilyin: Add scenario for 'pc info -S ...'
