@pc
Feature: `pc` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-help
  Scenario: Show CLI help
    When I run "partcad --help"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Increase the level of verbosity"
    And STDOUT should contain "Decrease the level of verbosity"
    And STDOUT should contain "Plain logging output. Do not use colors or animations."
    And STDOUT should contain "Package path (a YAML file or a directory with"
    And STDOUT should contain "Format output with prefixes"
    And STDOUT should contain "Initialize a new package"
    And STDOUT should contain "Install package dependencies"
    And STDOUT should contain "List available packages"

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

  @pc-format @pc-format-level @pc-version
  Scenario: Use log level as output prefix
    When I run "partcad --format=level version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^INFO PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^INFO PartCAD CLI version: \d+\.\d+\.\d+$"

  @pc-format @pc-format-time @pc-version
  Scenario: Use time with milliseconds as output prefix
    When I run "partcad --format=time version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD CLI version: \d+\.\d+\.\d+$"
    And the command should exit with a status code of "0"

  @pc-format @pc-format-path @pc-version
  Scenario: Use source file path and line number as output prefix
    When I run "partcad --format=path version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD CLI version: \d+\.\d+\.\d+$"

  Scenario: Handle non-existent package configuration
    When I run "partcad -p /nonexistent/path/partcad.yaml version"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Configuration file not found"

  Scenario: Handle invalid package configuration
    Given a file named "$WORKSPACE/partcad.yaml" with content:
      """
      invalid:
        yaml: [
      """
    When I run "partcad -p $WORKSPACE/partcad.yaml version"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid configuration file"
