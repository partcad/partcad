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

  @pc-info @add-assembly
  Scenario: Add assembly from `logo.assy` file
    Given a file named "partcad.yaml" with content:
      """
      parts:
        invalid:
          type: cadquery
      """
    Given a file named "invalid.py" with content:
      """
      import cadquery as cq

      This is not a valid CadQuery script
      """
    When I run command:
      """
      pc info invalid
      """
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Error"
    And STDOUT should contain "This is not a valid CadQuery script"

  @success @pc-info
  Scenario: Show 'Url' & 'Path' as package info for remote imports(git/tar)
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        rob:
          type: git
          relPath: robotics/parts
          url: https://github.com/partcad/partcad-index.git
          revision: main
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

  @success @pc-info
  Scenario: `pc info -P` looks the object up in the given package
    Given a directory named "sub" exists
    And a file named "sub/test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    And a file named "sub/partcad.yaml" with content:
      """
        parts:
          test:
            type: scad
      """
    And a file named "partcad.yaml" with content:
      """
        import:
          sub:
            path: sub
      """
    When I run "pc info -P //sub test"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Path: '//sub'"

  @success @pc-info
  Scenario: `pc info` without an object shows the current package
    Given a file named "partcad.yaml" with content:
      """
      desc: A sample PartCAD package
      parts:
        cube:
          type: cadquery
          path: cube.py
      """
    And a file named "cube.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      shape = cq.Workplane("front").box(10, 10, 10)
      show_object(shape)
      """
    When I run "pc info"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Path: '//'"
    And STDOUT should contain "sample PartCAD package"

  @success @pc-info
  Scenario: `pc info` reports what was measured when the part was built
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: cadquery
          path: block.py
      """
    And a file named "block.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      show_object(cq.Workplane("front").box(10, 20, 30))
      """
    When I run "pc info block"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "BoundingBox"
    And STDOUT should contain "'size': [10.0, 20.0, 30.0]"
    And STDOUT should contain "Volume: 6000.0"
    And STDOUT should contain "Solids: 1"

  @success @pc-info
  Scenario: `pc info -i` on a parametrized interface
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        m:
          type: basic
          circle: "%size / 2%"
          parameters:
            size:
              type: float
              default: 3.0

      interfaces:
        m:
          desc: Abstract %size%mm circular interface
          abstract: True
          parameters:
            size:
              type: float
              default: 3.0
          ports:
            m:
              location: [[0, 0, 0], [0, 0, 1], 0]
              sketch: m
              params:
                size: "%size%"
        m-thru:
          desc: "%depth%mm thick through hole of %size%mm diameter"
          parameters:
            size: 3.0
            depth: 3.0
          inherits:
            "m;size=%size%": thru
        m3-thru-3:
          alias: "m-thru;size=3,depth=3"
      """
    When I run command:
      """
      pc info -i m-thru
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "3mm thick through hole of 3mm diameter"
    When I run command:
      """
      pc info -i "m-thru;size=4,depth=2"
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "'m-thru;depth=2,size=4'"
    And STDOUT should contain "2mm thick through hole of 4mm diameter"
    And STDOUT should contain "'size': 4.0"
    When I run command:
      """
      pc info -i -p size=5 m-thru
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "3mm thick through hole of 5mm diameter"
    When I run command:
      """
      pc info -i m3-thru-3
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "3mm thick through hole of 3mm diameter"
    And STDOUT should contain "'alias': 'm-thru;size=3,depth=3'"
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
  #         revision: main
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
