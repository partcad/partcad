Feature: List Interfaces Command
  As a PartCAD user
  I want to list interfaces recursively
  So that I can view all available interfaces in the project

  Scenario: List interfaces recursively
    Given I have a PartCAD project with interfaces
    When I run "pc list-interfaces -r"
    Then I should see a list of all interfaces
    And the output should include nested interfaces
