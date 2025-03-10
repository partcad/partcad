@cli @import @assembly
Feature: `pc import assembly` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a directory named "input_files" exists
    And I copy file "examples/feature_import/AeroAssembly.step" to "input_files/AeroAssembly.step" inside test workspace
    And a file named "partcad.yaml" with content:
      """
      dependencies:
      sketches:
      parts:
      assemblies:
      """

  @step
  Scenario: Import STEP assembly into the project
    When I run "pc import assembly input_files/AeroAssembly.step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Successfully created assembly file"
    And a file named "AeroAssembly/AeroAssembly.assy" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
      parts:
        AeroAssembly/AeroFrameAssembly_solid1:
          type: step
        AeroAssembly/AeroFrameAssembly_solid2:
          type: step
        AeroAssembly/AeroFrameAssembly_solid3:
          type: step
        AeroAssembly/AeroFrame_Plate:
          type: step
        AeroAssembly/AeroFrame_Cap:
          type: step
        AeroAssembly/MirrorAeroFrameAssembly_solid1:
          type: step
        AeroAssembly/MirrorAeroFrameAssembly_solid2:
          type: step
        AeroAssembly/MirrorAeroFrameAssembly_solid3:
          type: step
      assemblies:
        AeroAssembly/AeroAssembly:
          type: assy
      """

  @error
  Scenario: Reject non-existent STEP file as assembly
    When I run "pc import assembly input_files/NonExistentAssembly.step"
    Then the command should exit with a status code of "2"

  @error
  Scenario: Reject unsupported file format as assembly
    Given I copy file "examples/feature_convert/stl/cube.stl" to "input_files/cube.stl" inside test workspace
    When I run "pc import assembly input_files/cube.stl"
    Then the command should exit with a status code of "1"
