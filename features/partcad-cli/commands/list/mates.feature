Feature: List mates with recursive flag
  As a PartCAD user
  I want to list all mates recursively
  So that I can see the complete mate hierarchy

  Scenario: Successfully list mates recursively
    Given I have a project with nested mates
    When I run "pc list-mates -r"
    Then the command should succeed
    And the output should contain all mates in hierarchical order

  Scenario: List mates with no recursive content
    Given I have a project with only top-level mates
    When I run "pc list-mates -r"
    Then the command should succeed
    And the output should match the non-recursive listing
