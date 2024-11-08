@cli @list-packages
Feature: List PartCAD packages

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @failure @pc-list
  Scenario: List all PartCAD packages in uninitialized directory
    When I run "pc --no-ansi list"
    Then the command should exit with a status code of "1"
    And STDOUT should not contain "PartCAD packages:"
    And STDOUT should not contain "<none>"

  @success @pc-init @pc-list
  Scenario: List all PartCAD packages
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "pc --no-ansi list"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "PartCAD packages:"
    And STDOUT should not contain "<none>"

  @success @pc-init @pc-install @pc-list
  Scenario: List all PartCAD packages
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "pc --no-ansi install"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: Print packages even when --no-ansi provided
    When I run "pc list"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD packages:"
    And STDOUT should not contain "<none>"
