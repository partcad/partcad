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
    And a file named "partcad.yaml" should have YAML content:
      """
      import: 
        pub: 
          type: git
          url: https://github.com/openvmp/partcad-index.git
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
      import: 
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
