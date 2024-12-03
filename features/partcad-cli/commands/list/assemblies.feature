Feature: List Assemblies Command
  As a PartCAD user
  I want to list assemblies recursively
  So that I can view all assemblies in the project

  Scenario: List assemblies recursively
    Given I have a PartCAD project with assemblies
    When I run "pc list-assemblies -r"
    Then I should see a list of all assemblies
    And the output should include nested assemblies
