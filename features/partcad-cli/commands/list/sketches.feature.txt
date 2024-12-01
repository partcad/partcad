Feature: List sketches recursively
  As a PartCAD user
  I want to list all sketches recursively
  So that I can see the complete sketch hierarchy

  Scenario: List sketches in a complex project
    Given I have a project with nested sketches
    When I run "pc list-sketches -r"
    Then the command should succeed
    And the output should contain all sketches in hierarchical order
    And each sketch should display its parent-child relationships

  Scenario: List sketches in an empty project
    Given I have a project with no sketches
    When I run "pc list-sketches -r"
    Then the command should succeed
    And the output should indicate no sketches found
