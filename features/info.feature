@cli @pc-info @add-assembly
Feature: `pc info` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-info @add-assembly
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
    Given a file named "cylinder.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      shape = cq.Workplane("front").circle(10.0).extrude(10.0)
      show_object(shape)
      """
    Given a file named "cube.py" with content:
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
    Given a file named "primitive.assy" with content:
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
      partcad info cube
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad info cylinder
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad info -a primitive
      """
    Then the command should exit with a status code of "0"

  @success @pc-info
  Scenario: Show 'Url' & 'Path' as package info for remote imports(git/tar)
    Given a file named "partcad.yaml" with content:
      """
      import:
        rob:
          type: git
          relPath: robotics/parts
          url: https://github.com/partcad/partcad-index.git
      """
    When I run "pc info /rob/dfrobot:motion/rubber_wheel_136_24"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "github.com"
    And STDOUT should contain "Url: 'https://www.dfrobot.com/"
    And STDOUT should contain "ImportUrl: 'https://github.com/"
    And STDOUT should contain "Path: '//rob/dfrobot'"

  @success @pc-info
  Scenario: Show 'Path' as package info for local imports
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    And a file named "partcad.yaml" with content:
      """
        parts:
          test:
            type: scad
      """
    When I run "pc info test"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Path: '//'"
# And STDOUT should contain "cube" in the parts list
# And STDOUT should contain "cylinder" in the parts list
# And STDOUT should contain valid location coordinates
# When I run command with invalid assembly name:
# """
# partcad info -a nonexistent
# """
# Then the command should exit with a non-zero status code


  # Background: Initialize Public PartCAD project
  #   Given I am in "/tmp/sandbox/behave" directory
  #   And I have temporary $HOME in "/tmp/sandbox/home"
  #   And a file named "partcad.yaml" does not exist
  #   When I run "pc --no-ansi init"
  #   Then the command should exit with a status code of "0"
  #   And a file named "partcad.yaml" should be created with content:
  #     """
  #     dependencies:
  #       pub:
  #         type: git
  #         url: https://github.com/openvmp/partcad-index.git
  #     parts:
  #     assemblies:
  #     """

  # @pc-info
  # Scenario: Show part details
  #   When I run "pc info //pub/std/metric/cqwarehouse:fastener/hexhead-din931"
  #   Then the command should exit with a status code of "0"
  #   And STDOUT should contain "'name': 'fastener/hexhead-din931',"
  #   And STDOUT should contain "'orig_name': 'fastener/hexhead-din931',"

  # @pc-info
  # Scenario: Show simplified part information
  #   When I run "pc info -s //pub/std/metric/m:m3"
  #   Then the command should exit with a status code of "0"
  #   And STDOUT should contain only essential fields
  #   And STDOUT should not contain detailed specifications

  # @pc-info
  # Scenario: Show interactive part information
  #   When I run "pc info -i //pub/std/metric/m:m3-screw"
  #   Then the command should exit with a status code of "0"
  #   And an interactive viewer should be launched
  #   And the viewer should display the part model
