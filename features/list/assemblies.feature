@cli @list-assemblies
Feature: `pc list assemblies` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Add assembly from `logo.assy` file
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          desc: This is a cube from examples
          parameters:
            width:
              default: 10.0
            length:
              default: 10.0
            height: 10.0
          aliases: ["box"]
        cylinder:
          type: cadquery
          path: cylinder.py
          desc: This is a cylinder from examples
      """
    And a file named "cylinder.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      shape = cq.Workplane("front").circle(10.0).extrude(10.0)
      show_object(shape)
      """
    And a file named "cube.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      width = 10.0
      length = 10.0
      height = 10.0

      shape = cq.Workplane("front").box(width, length, height)

      show_object(shape)
      """
    And a file named "primitive.assy" with content:
      """
      links:
        - part: cube
          location: [[0,0,0], [0,0,1], 0]
        - part: cylinder
          location: [[0,0,5], [0,0,1], 0]
      """
    When I run command:
      """
      partcad add assembly assy primitive.assy
      """
    Then the command should exit with a status code of "0"
    # INFO:  Adding the assembly primitive.assy of type assy
    When I run command:
      """
      partcad list assemblies
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: InitCtx:"
    Then STDOUT should contain "PartCAD assemblies:"
    Then STDOUT should contain "primitive"
    Then STDOUT should contain "Total: 1"
    Then STDOUT should contain "DONE: ListAssy: //"

#   @ai-openscad @failure
#   Scenario: Fail to add assembly with missing referenced parts
#     Given a file named "missing.assy" with content:
#       """
#       links:
#         - part: /nonexistent_part:bone
#           location: [[0, 0, 0], [0, 0, 1], 0]
#       """
#     When I run "partcad add-assembly assy missing.assy"
#     Then the command should exit with a status code of "1"
#     And STDERR should contain "Referenced part not found"


# Feature: List Assemblies Command
#   As a PartCAD user
#   I want to list assemblies recursively
#   So that I can view all assemblies in the project
#
#   Scenario: List assemblies recursively
#     Given I have a PartCAD project with assemblies
#     When I run "pc list-assemblies -r"
#     Then I should see a list of all assemblies
#     And the output should include nested assemblies

  @wip
  Scenario: List empty project
    Given I have an empty PartCAD project
    When I run "pc list-assemblies -r"
    Then I should see "No assemblies found"

  @wip
  Scenario: List with depth limit
    Given I have a PartCAD project with nested assemblies
    When I run "pc list-assemblies -r --depth 2"
    Then I should see assemblies up to depth 2
    And deeper nested assemblies should not be listed
