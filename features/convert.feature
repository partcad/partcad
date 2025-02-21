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
          parameters:
            width:
              type: int
              default: 2
              name: width
            height:
              type: int
              default: 2
              name: height
        cube_enrich:
          type: enrich
          source: ":cube"
          with:
            height: 4
            width: 4
        cube_alias:
          type: alias
          source: ":cube;width=10,height=10"
      """

  @stl @dry-run
  Scenario: Dry-run conversion for part `cube`
    When I run "pc convert :cube -t step --dry-run"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "[Dry Run] No changes made for 'cube'."

  @step @directory
  Scenario: Conversion with specified output directory for part `cube`
    Given a directory named "output" exists
    When I run "pc convert :cube -t step -O output"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting 'cube': stl to step"
    And a file named "output/cube.step" should exist

  @error
  Scenario: Failure due to missing object argument
    When I run "pc convert -t step"
    Then the command should exit with a status code of "2"

  @error
  Scenario: Failure due to non-existent object
    When I run "pc convert :nonexistent -t brep"
    Then the command should exit with a status code of "2"

  @error
  Scenario: Conversion failure due to unsupported conversion
    When I run "pc convert :cube_build123d -t step"
    Then the command should exit with a status code of "2"

  @enrich @resolve
  Scenario: Resolving an enrich part
    When I run "pc convert :cube_enrich"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting 'cube_enrich': enrich to stl"
    And a file named "cube_enrich.stl" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      parts:
        cube:
          type: stl
          path: cube.stl
          parameters:
            width:
              type: int
              default: 2
              name: width
            height:
              type: int
              default: 2
              name: height

        cube_enrich:
          type: stl
          path: cube_enrich.stl
          parameters:
            width:
              type: int
              default: 4
              name: width
              min: 2
              max: 2
            height:
              type: int
              default: 4
              name: height
              min: 2
              max: 2
          manufacturable: True

        cube_alias:
          type: alias
          source: ":cube;width=10,height=10"
      """

  @enrich @error
  Scenario: Resolving a non-existent enrich part
    When I run "pc convert :nonexistent_enrich"
    Then the command should exit with a status code of "2"

  @enrich @convert
  Scenario: Resolving and converting an enrich part
    When I run "pc convert :cube_enrich -t brep"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting 'cube_enrich': enrich to stl"
    And STDOUT should contain "Converting 'cube_enrich': stl to brep"
    And a file named "cube_enrich.brep" should exist

  @enrich @output-dir
  Scenario: Resolving an enrich part with a specified output directory
    Given a directory named "output" exists
    When I run "pc convert :cube_enrich -t step -O output"
    Then the command should exit with a status code of "0"
    And a file named "output/cube_enrich.step" should exist

  @alias @resolve
  Scenario: Resolving an alias part
    When I run "pc convert cube_alias"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting 'cube_alias': alias to stl"
    And a file named "cube_alias.stl" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      parts:
        cube:
          type: stl
          path: cube.stl
          parameters:
            width:
              type: int
              default: 2
              name: width
            height:
              type: int
              default: 2
              name: height

        cube_enrich:
          type: enrich
          source: ":cube"
          with:
            height: 4
            width: 4

        cube_alias:
          type: stl
          path: cube_alias.stl
          parameters:
            width:
              type: int
              default: 10
              name: width
              min: 2
              max: 2
            height:
              type: int
              default: 10
              name: height
              min: 2
              max: 2
          manufacturable: True
      """

  @alias @convert
  Scenario: Resolving and converting an alias part
    When I run "pc convert :cube_alias -t brep"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting 'cube_alias': alias to stl"
    And STDOUT should contain "Converting 'cube_alias': stl to brep"
    And a file named "cube_alias.brep" should exist

  @alias @output-dir
  Scenario: Resolving an alias part with a specified output directory
    Given a directory named "output" exists
    When I run "pc convert :cube_alias -t step -O output"
    Then the command should exit with a status code of "0"
    And a file named "output/cube_alias.step" should exist

  @alias @error
  Scenario: Resolving a non-existent alias part
    When I run "pc convert :nonexistent_alias"
    Then the command should exit with a status code of "2"
