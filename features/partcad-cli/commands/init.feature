@cli
Feature: Initialize a new PartCAD package

  @pc-init
  Scenario: Initialize a new PartCAD package in the current directory
    Given I am in "/tmp/sandbox/behave" directory
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
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
  Scenario: Initialize a new PartCAD package as private
    Given I am in "/tmp/sandbox/behave" directory
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import: 
      parts:
      assemblies:
      """
    And the package should be marked as private

  @pc-init @option-private @failure
  Scenario: Fail second initialize
    Given I am in "/tmp/sandbox/behave" directory
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then a file named "partcad.yaml" should be created
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "1"
    And STDERR should contain "File already exists: partcad.yaml"
    And STDERR should contain "Failed creating 'partcad.yaml'!"
