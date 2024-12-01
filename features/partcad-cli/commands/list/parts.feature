@cli @list-packages
Feature: `pc list parts` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-init @pc-install @pc-list @pc-list-parts
  Scenario: List parts
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad --no-ansi install"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: Print parts even when --no-ansi provided
    When I run "partcad list parts"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD parts:"
    And STDOUT should contain "Total:"
    And STDOUT should not contain "<none>"

  @success @pc-init @pc-install @pc-list @pc-list-parts @pc-list-parts-recursively
  Scenario: List parts recursively
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad --no-ansi install"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: Print parts even when --no-ansi provided
    When I run "partcad list parts -r"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD parts:"
    And STDOUT should contain "Total:"
    And STDOUT should not contain "<none>"
