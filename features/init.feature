@cli
Feature: `pc init` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-init
  Scenario: Initialize new package as public
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "PartCAD configuration file is not found"
    And a file named "partcad.yaml" should have YAML content:
      """
      pythonVersion: ">=\\d+\\.\\d+"
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
        pub:
          type: git
          url: https://github.com/partcad/partcad-index.git
      sketches:
      parts:
      assemblies:
      """

  @pc-init @private
  Scenario: Initialize new package as private
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      pythonVersion: ">=\\d+\\.\\d+"
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      """
    And the package should be marked as private

  @pc-init @option-private @failure
  Scenario: Fail initializing package when `partcad.yaml`already exists
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then a file named "partcad.yaml" should be created
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "1"
    And STDERR should contain "File already exists: partcad.yaml"
    And STDERR should contain "Failed creating 'partcad.yaml'!"

  @wip @pc-init @failure
  Scenario: Fail initializing package with insufficient permissions
    Given I am in "/tmp/sandbox/behave" directory
    And the directory has read-only permissions
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Permission denied"

  @wip @pc-init @failure
  Scenario: Fail initializing with malformed existing YAML
    Given a file named "partcad.yaml" with content:
      """
      invalid:
        - yaml:
      content:
      """
    When I run "partcad --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid YAML format"
