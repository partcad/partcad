@cli @convert
Feature: `pc convert` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And I copy file "examples/feature_convert/stl/cube.stl" to "cube.stl" inside test workspace
    And a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: stl
          path: cube.stl
      """

  @stl @dry-run
  Scenario: Dry-run conversion for part `cube`
    When I run "pc convert cube -t step --dry-run"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "[Dry Run]"
    And STDOUT should contain "cube.step"

  @step @directory
  Scenario: Conversion with specified output directory for part `cube`
    Given a directory named "output" exists
    When I run "pc convert cube -t step -O output"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Conversion of 'cube' to 'step' completed."
    And a file named "output/cube.step" should exist

  @error
  Scenario: Failure due to missing object argument
    When I run "pc convert -t step"
    Then the command should exit with a status code of "2"

  @error
  Scenario: Failure due to non-existent object
    When I run "pc convert :nonexistent -t brep"
    Then the command should exit with a status code of "1"

  @error
  Scenario: Conversion failure due to unsupported conversion
    When I run "pc convert :cube_build123d -t step"
    Then the command should exit with a status code of "1"
