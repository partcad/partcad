@cli @add-assembly
Feature: `pc list assemblies` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Add assembly from `logo.assy` file
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        circle_01:
          type: basic
          desc: The shortest way to create a basic circle in PartCAD
          circle: 5
      """
    When I run command:
      """
      cp -v $PARTCAD_ROOT/examples/produce_sketch_basic/circle_01.svg ./
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      pc list sketches
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: InitCtx:"
    Then STDOUT should contain "PartCAD sketches:"
    Then STDOUT should contain "circle_01"
    Then STDOUT should contain "The shortest way to create a basic circle in PartCAD"
    Then STDOUT should contain "Total: 1"
    Then STDOUT should contain "DONE: ListSketches: //:"

# Feature: List sketches recursively
#   As a PartCAD user
#   I want to list all sketches recursively
#   So that I can see the complete sketch hierarchy

#   Scenario: List sketches in a complex project
#     Given I have a project with nested sketches
#     When I run "pc list-sketches -r"
#     Then the command should succeed
#     And the output should contain all sketches in hierarchical order
#     And each sketch should display its parent-child relationships

#   Scenario: List sketches in an empty project
#     Given I have a project with no sketches
#     When I run "pc list-sketches -r"
#     Then the command should succeed
#     And the output should indicate no sketches found
