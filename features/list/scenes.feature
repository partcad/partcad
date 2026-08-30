@cli @list-scenes
Feature: `pc list scenes` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Add a scene from a `bench.assy` file
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          desc: This is a cube from examples
        cylinder:
          type: cadquery
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

      shape = cq.Workplane("front").box(10.0, 10.0, 10.0)
      show_object(shape)
      """
    And a file named "bench.assy" with content:
      """
      links:
        - part: cube
          location: [[0,0,0], [0,0,1], 0]
        - part: cylinder
          location: [[30,0,0], [0,0,1], 0]
      """
    When I run command:
      """
      partcad add scene assy bench.assy
      """
    Then the command should exit with a status code of "0"
    # The very same file in an 'assemblies:' section would be an assembly; the
    # section it is declared in is what makes it a scene.
    When I run command:
      """
      partcad list scenes
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "PartCAD scenes:"
    Then STDOUT should contain "bench"
    Then STDOUT should contain "Total: 1"
    Then STDOUT should contain "DONE: ListScenes: //"
    # And it is a namespace of its own: nothing was added to the assemblies.
    When I run command:
      """
      partcad list assemblies
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "<none>"
