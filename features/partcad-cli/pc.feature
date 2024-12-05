@pc
Feature: `pc` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-help
  Scenario: Show CLI help
    When I run "partcad --help"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Increase the level of verbosity"
    And STDERR should contain "Decrease the level of verbosity"
    And STDERR should contain "Plain logging output. Do not use colors or animations."
    And STDERR should contain "Package path (a YAML file or a directory with"
    And STDERR should contain "Log prefix format"
    And STDERR should contain "Initialize a new PartCAD package in this directory "
    And STDERR should contain "Download and prepare all imported packages "
    And STDERR should contain "List components"

  @pc-verbose @pc-status
  Scenario: Show DEBUG messages with increased verbosity
    When I run "partcad -v status"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: check that DEBUG prefix is present
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should contain "Tar cache size:"
    And STDOUT should contain "Git cache size:"
    And STDOUT should contain "Runtime environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: this:"

  @pc-quiet @pc-status
  Scenario: Do not show INFO messages with decreased verbosity
    When I run "partcad -q status"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: check that INFO prefix is not present
    And STDOUT should not contain "PartCAD version:"
    And STDOUT should not contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should not contain "Tar cache size:"
    And STDOUT should not contain "Git cache size:"
    And STDOUT should not contain "Runtime environments size:"
    And STDOUT should not contain "Total internal data storage size:"
    And STDOUT should not contain "DONE: Status: this:"

  @pc-no-ansi @pc-status
  Scenario: Do not show ANSI codes
    When I run "partcad --no-ansi status"
    Then the command should exit with a status code of "0"
    # TODO: @alexanderilyin: strip ANSI codes and compare
    And the following messages should not be present:
      """
      PartCAD version:
      Internal data storage location: /tmp/sandbox/home/partcad-cli
      Tar cache size:
      Git cache size:
      Runtime environments size:
      Total internal data storage size:
      DONE: Status: this:
      """

  @pc-path @pc-version
  Scenario: Read package configuration from arbitrary location
    Given "WORKSPACE" env var is set to the temp dir "/tmp/sandbox/tmp"
    And a file named "$WORKSPACE/partcad.yaml" with content:
      """
      import:
      parts:
      assemblies:
      """
    When I run "partcad -p $WORKSPACE/partcad.yaml version"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "Package path location: /tmp/sandbox/behave"

  @wip @pc-format @pc-format-level @pc-version
  Scenario: Use log level as output prefix
    When I run "partcad --format=level version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^INFO PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^INFO PartCAD CLI version: \d+\.\d+\.\d+$"

  @wip @pc-format @pc-format-time @pc-version
  Scenario: Use time with milliseconds as output prefix
    When I run "partcad --format=time version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD CLI version: \d+\.\d+\.\d+$"
    And the command should exit with a status code of "0"

  @wip @pc-format @pc-format-path @pc-version
  Scenario: Use source file path and line number as output prefix
    When I run "partcad --format=path version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD CLI version: \d+\.\d+\.\d+$"

  Scenario: Handle non-existent package configuration
    When I run "partcad -p /nonexistent/path/partcad.yaml version"
    Then the command should exit with a status code of "2"
    And STDERR should contain "Invalid value for '-p': Path '/nonexistent/path/partcad.yaml' does not exist."

  Scenario: Handle invalid package configuration
    Given a file named "partcad.yaml" with content:
      """
      invalid:
        yaml: [
      """
    When I run "partcad -p partcad.yaml list"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid configuration file"
