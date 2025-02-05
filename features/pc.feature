@pc
Feature: `pc` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-help
  Scenario: Show CLI help
    When I run "pc --help"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Increase verbosity level"
    And STDOUT should contain "Decrease verbosity level"
    # TODO-60: Due to different terminal size in CI ' or animations' is wrapped to the next line
    And STDOUT should contain "Produce plain text logs without colors"
    # TODO-61: Due to different terminal size in CI' (YAML file or directory with 'partcad.yaml')' is wrapped to the next line
    And STDOUT should contain "Specify the package path"
    And STDOUT should contain "Set the log prefix format"
    And STDOUT should contain "Create a new PartCAD package in the current directory "
    And STDOUT should contain "Download and set up all imported packages "
    And STDOUT should contain "List components"

  @pc-verbose @pc-status
  Scenario: Show DEBUG messages with increased verbosity
    When I run "pc -v status"
    Then the command should exit with a status code of "0"
    # TODO-62: @alexanderilyin: check that DEBUG prefix is present
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should contain "Tar cache size:"
    And STDOUT should contain "Git cache size:"
    And STDOUT should contain "Runtime environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: this:"

  @pc-quiet @pc-status
  Scenario: Do not show INFO messages with decreased verbosity
    When I run "pc -q status"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "INFO:partcad:PartCAD version:"
    And STDOUT should not contain "INFO:partcad:Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should not contain "INFO:partcad:Tar cache size:"
    And STDOUT should not contain "INFO:partcad:Git cache size:"
    And STDOUT should not contain "INFO:partcad:Runtime environments size:"
    And STDOUT should not contain "INFO:partcad:Total internal data storage size:"
    And STDOUT should not contain "INFO:partcad:DONE: Status: this:"

  @pc-no-ansi @pc-status
  Scenario: Do not show ANSI codes
    When I run "pc --no-ansi status"
    Then the command should exit with a status code of "0"
    And STDERR should contain "INFO:partcad:PartCAD version:"
    And STDERR should contain "INFO:partcad:Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDERR should contain "INFO:partcad:Tar cache size:"
    And STDERR should contain "INFO:partcad:Git cache size:"
    And STDERR should contain "INFO:partcad:Runtime environments size:"
    And STDERR should contain "INFO:partcad:Total internal data storage size:"
    And STDERR should contain "INFO:partcad:DONE: Status: this:"

  @pc-path @pc-version
  Scenario: Read package configuration from arbitrary location
    Given "WORKSPACE" env var is set to the temp dir "/tmp/sandbox/tmp"
    And a file named "$WORKSPACE/partcad.yaml" with content:
      """
      dependencies:
      sketches:
      parts:
      assemblies:
      """
    When I run "pc -p $WORKSPACE/partcad.yaml version"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "Package path location: /tmp/sandbox/behave"

  @wip @pc-format @pc-format-level @pc-version
  Scenario: Use log level as output prefix
    When I run "pc --level version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^INFO PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^INFO PartCAD CLI version: \d+\.\d+\.\d+$"

  @wip @pc-format @pc-format-time @pc-version
  Scenario: Use time with milliseconds as output prefix
    When I run "pc --time version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD CLI version: \d+\.\d+\.\d+$"
    And the command should exit with a status code of "0"

  @wip @pc-format @pc-format-path @pc-version
  Scenario: Use source file path and line number as output prefix
    When I run "pc --path version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD Python Module version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD CLI version: \d+\.\d+\.\d+$"

@wip
  Scenario: Handle non-existent package configuration
    When I run "pc -p /nonexistent/path/partcad.yaml version"
    Then the command should exit with a status code of "2"
    And STDERR should contain "Invalid value for '-p': Path '/nonexistent/path/partcad.yaml' does not exist."

  Scenario: Handle invalid package configuration
    Given a file named "partcad.yaml" with content:
      """
      invalid:
        yaml: [
      """
    When I run "pc -p partcad.yaml list"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid configuration file"

  @wip
  Scenario: Handle empty package configuration
    Given a file named "partcad.yaml" with content:
      """
      """
    When I run "pc -p partcad.yaml list packages"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Empty configuration file"

@wip
  Scenario: Handle non-existent package configuration
    When I run "pc -p /nonexistent/path/partcad.yaml version"
    Then the command should exit with a status code of "2"
    And STDERR should contain "Invalid value for '-p': Path '/nonexistent/path/partcad.yaml' does not exist."
