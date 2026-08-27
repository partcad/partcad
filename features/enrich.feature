@cli @pc-enrich
Feature: `enrich` objects

  An 'enrich' is a reference to an instance of the object it enriches: the same
  object, with the parameter values it asks for. What builds that object is the
  declaration of the object itself, so anything an enrich says about *how* it
  is built has nothing to act on, and is reported rather than dropped in
  silence.

  Background: Create temporary environment
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "cube.py" with content:
      """
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      width = 10.0

      shape = cq.Workplane("front").box(width, width, width)
      show_object(shape)
      """

  @success @pc-enrich @pc-enrich-ignored
  Scenario: Build-affecting properties on an enrich are ignored, and said so
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          path: cube.py
          parameters:
            width:
              default: 10.0
        cube_wide:
          type: enrich
          source: cube
          desc: A wider cube
          with:
            width: 20.0
          path: elsewhere.py
          pythonRequirements: ["numpy"]
          parameters:
            width:
              default: 30.0
      """
    When I run "partcad list parts"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "WARN: The enrich '//:cube_wide' ignores 'parameters', 'path', 'pythonRequirements'"
    And STDOUT should contain "cube_wide"

  @success @pc-enrich @pc-enrich-ignored
  Scenario: An enrich that says nothing about how the object is built is quiet
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          path: cube.py
          parameters:
            width:
              default: 10.0
        cube_wide:
          type: enrich
          source: cube
          desc: A wider cube
          with:
            width: 20.0
      """
    When I run "partcad list parts"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "WARN:"
