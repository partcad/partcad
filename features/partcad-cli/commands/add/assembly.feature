@wip @cli @add-assembly
Feature: Add an assembly

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
      parts:
      assemblies:
      """    

  @ai-openscad
  Scenario: Add assembly from file
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
    When I run "pc add-assembly assy logo.assy"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
      assemblies:
        logo:
          type: assy
      """
