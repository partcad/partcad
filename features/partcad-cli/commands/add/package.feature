@wip @cli @add-package
Feature: Test cli_add function
  As a user
  I want to add an import to a project
  So that I can use the imported package

  @success @pc-init @pc-install @pc-list
  Scenario: List all PartCAD packages in uninitialized directory
    # rm -rf partcad.yaml
    Given I am in "/tmp/sandbox/behave" directory
    # rm -rf ~/.partcad/
    And I have temporary $HOME in "/tmp/sandbox/home"
    # pc init -p
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    # pc add OpenVMP-robots https://github.com/openvmp/openvmp-models.git
    When I run "pc add OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
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
    When I run "pc list"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD packages:"
    And STDOUT should contain "OpenVMP-robots"
    And STDOUT should not contain "<none>"
