@cli
Feature: `pc version` command
  As a user
  I want to run the version command
  So that I can see the PartCAD and PartCAD CLI versions

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-version @success
  Scenario: Show version information
    When I run "partcad version"
    Then STDERR should contain "PartCAD version:"
    And STDERR should contain "PartCAD CLI version:"
    And command takes less than "2" seconds
    And the command should exit with a status code of "0"

# TODO: @alexanderilyin: find a way to compare cli version with the package version
# python -c 'import partcad; print(partcad.__version__)'
