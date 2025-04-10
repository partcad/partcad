@cli @import @part
Feature: `pc import` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a directory named "input_files" exists
    And I copy file "examples/feature_convert_part/stl/cube.stl" to "input_files/cube.stl" inside test workspace
    And a file named "partcad.yaml" with content:
      """
      dependencies:
      sketches:
      parts:
      assemblies:
      """

  @stl
  Scenario: Import STL part into the project
    When I run "pc import part input_files/cube.stl"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Part 'cube' imported successfully."
    And a file named "cube.stl" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        cube:
          type: stl
      assemblies:
      """

  @stl @conversion
  Scenario: Import STL part and convert to STEP
    When I run "pc import part input_files/cube.stl -t step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Ad-hoc conversion successful"
    And STDOUT should contain "Successfully imported part"
    And a file named "cube.step" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        cube:
          type: step
      assemblies:
      """

  @error
  Scenario: Reject non-existent file import
    When I run "pc import part input_files/nonexistent.stl"
    Then the command should exit with a status code of "2"

  @error
  Scenario: Reject invalid file format conversion
    Given I copy file "examples/feature_convert_part/stl/cube.stl" to "input_files/cube.stl" inside test workspace
    When I run "pc import part stl input_files/cube.stl -t unknown_format"
    Then the command should exit with a status code of "2"

  @step
  Scenario: Import and convert a STEP file
    Given a file named "input_files/part.step" with content:
      """
      -- STEP file content --
      """
    When I run "pc import part input_files/part.step"
    Then the command should exit with a status code of "0"
    And a file named "part.step" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        part:
          type: step
      assemblies:
      """

  @stl
  Scenario: Import and convert STL file to multiple formats
    When I run "pc import part input_files/cube.stl -t brep"
    Then the command should exit with a status code of "0"
    And a file named "cube.brep" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        cube:
          type: brep
      assemblies:
      """

  @3mf
  Scenario: Import 3MF file
    Given a file named "input_files/design.3mf" with content:
      """
      -- 3MF file content --
      """
    When I run "pc import part input_files/design.3mf"
    Then the command should exit with a status code of "0"
    And a file named "design.3mf" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        design:
          type: 3mf
      assemblies:
      """
