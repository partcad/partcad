@wip @cli @add-assembly
Feature: Add an assembly

  Background: Initialize Public PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
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
  Scenario: Show info about a part
    When I run "pc info /pub/std/metric/cqwarehouse:fastener/hexhead-din931"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "'name': 'fastener/hexhead-din931',"
    And STDOUT should contain "'orig_name': 'fastener/hexhead-din931',"