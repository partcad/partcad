@cli
Feature: Display the state of internal data used by PartCAD

  Background: Initialize Private PartCAD project
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

  @pc-init @pc-status @success
  Scenario: Display the state of internal data used by PartCAD
    When I run "partcad status"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: $HOME/.partcad"
    And STDOUT should contain "Tar cache size:"
    And STDOUT should contain "Git cache size:"
    And STDOUT should contain "Runtime environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: this:"
