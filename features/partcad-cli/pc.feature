@pc
Feature: Display help information for PartCAD CLI

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-help
  Scenario: Display help information
    When I run "partcad --help"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Increase the level of verbosity"
    And STDOUT should contain "Decrease the level of verbosity"
    And STDOUT should contain "Plain logging output. Do not use colors or animations."
    And STDOUT should contain "Package path (a YAML file or a directory with"

  @pc-verbose @pc-status
  Scenario: -v Increase the level of verbosity
    When I run "partcad -v status"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should contain "Tar cache size:"
    And STDOUT should contain "Git cache size:"
    And STDOUT should contain "Runtime environments size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: this:"

  @pc-quiet @pc-status
  Scenario: -q Decrease the level of verbosity
    When I run "partcad -q status"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "PartCAD version:"
    And STDOUT should not contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should not contain "Tar cache size:"
    And STDOUT should not contain "Git cache size:"
    And STDOUT should not contain "Runtime environments size:"
    And STDOUT should not contain "Total internal data storage size:"
    And STDOUT should not contain "DONE: Status: this:"

  @pc-no-ansi @pc-status
  Scenario: --no-ansi Plain logging output. Do not use colors or animations.
    When I run "partcad --no-ansi status"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "PartCAD version:"
    And STDOUT should not contain "Internal data storage location: /tmp/sandbox/home/partcad-cli-"
    And STDOUT should not contain "Tar cache size:"
    And STDOUT should not contain "Git cache size:"
    And STDOUT should not contain "Runtime environments size:"
    And STDOUT should not contain "Total internal data storage size:"
    And STDOUT should not contain "DONE: Status: this:"

  @pc-path @pc-version
  Scenario: -p Package path (a YAML file or a directory with 'partcad.yaml')
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
  Scenario: --format
    When I run "partcad --format=level version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^INFO PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^INFO PartCAD CLI version: \d+\.\d+\.\d+$"

  @pc-format @pc-format-time @pc-version
  Scenario: --format
    When I run "partcad --format=time version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^\d{2}:\d{2}:\d{2}\.\d{3} INFO PartCAD CLI version: \d+\.\d+\.\d+$"
    And the command should exit with a status code of "0"

  @pc-format @pc-format-path @pc-version
  Scenario: --format
    When I run "partcad --format=path version"
    Then the command should exit with a status code of "0"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD version: \d+\.\d+\.\d+$"
    And STDERR should match the regex "^/.+\.py:\d+ PartCAD CLI version: \d+\.\d+\.\d+$"
