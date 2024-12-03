Feature: Supply quote generation
  As a PartCAD user
  I want to generate supply quotes
  So that I can estimate costs for my projects

  Scenario: Generate quote for available parts
    Given I have a project with standard parts
    When I run "pc supply quote --format json"
    Then the command should succeed
    And the output should contain valid pricing information
    And the response should be in JSON format

  Scenario: Handle quote for unavailable parts
    Given I have a project with custom parts
    When I run "pc supply quote"
    Then the command should succeed with warnings
    And the output should indicate which parts cannot be quoted
