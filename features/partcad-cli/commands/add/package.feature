@wip @cli @add-package
Feature: `pc add package` command
  As a user
  I want to add an import to a project
  So that I can use the imported package

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-init @pc-install @pc-list
  Scenario: List packages in uninitialized directory
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad add OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
    Then the command should exit with a status code of "0"
    # And a file named "$PWD/partcad.yaml" should have content:
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
        OpenVMP-robots:
          url: https://github.com/openvmp/openvmp-models.git
          type: git
      parts:
      assemblies:
      """
    When I run "partcad list"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD packages:"
    And STDOUT should contain "OpenVMP-robots"
    And STDOUT should not contain "<none>"
