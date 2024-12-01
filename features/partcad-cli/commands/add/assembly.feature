@wip @cli @add-assembly
Feature: `pc add assembly` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
      parts:
      assemblies:
      """
# TODO: Error case: Adding an assembly with invalid YAML syntax
# TODO: Error case: Adding an assembly with non-existent referenced parts
# TODO: Error case: Adding an assembly with duplicate name
# TODO: Success case: Adding multiple assemblies
# TODO: Success case: Adding an assembly with relative file paths

  @ai-openscad
  Scenario: Add assembly from `logo.assy` file
    Given a file named "logo.assy" with content:
      """
      links:
        - part: /produce_part_cadquery_logo:bone
          location: [[0, 0, 0], [0, 0, 1], 0]
        - part: /produce_part_cadquery_logo:bone
          location: [[0, 0, -2.5], [0, 0, 1], -90]
        - links:
            - part: /produce_part_cadquery_logo:head_half
              location: [[0, 0, 2.5], [0, 0, 1], 0]
            - part: /produce_part_cadquery_logo:head_half
              location: [[0, 0, 0], [0, 0, 1], -90]
          location: [[0, 0, 25], [1, 0, 0], 0]
        - part: /produce_part_step:bolt
          package:
          location: [[0, 0, 7.5], [0, 0, 1], 0]
      """
    When I run "partcad add-assembly assy logo.assy"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
      assemblies:
        logo:
          type: assy
      """

  @ai-openscad @failure
  Scenario: Fail to add assembly with invalid YAML syntax
    Given a file named "invalid.assy" with content:
      """
      links:
        - this is not valid yaml
      """
    When I run "partcad add-assembly assy invalid.assy"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid YAML syntax"

  @ai-openscad @failure
  Scenario: Fail to add assembly with missing referenced parts
    Given a file named "missing.assy" with content:
      """
      links:
        - part: /nonexistent_part:bone
          location: [[0, 0, 0], [0, 0, 1], 0]
      """
    When I run "partcad add-assembly assy missing.assy"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Referenced part not found"
