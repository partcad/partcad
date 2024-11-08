@cli @list-packages
Feature: `pc list packages` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @failure @pc-list
  Scenario: List packages in uninitialized directory
    When I run "partcad --no-ansi list"
    # TODO: @alexanderilyin: consider converting this scenario to a failure
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "PartCAD packages:"
    And STDOUT should not contain "<none>"

  @success @pc-init @pc-list
  Scenario: List packages
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad --no-ansi list"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "PartCAD packages:"
    And STDOUT should not contain "<none>"