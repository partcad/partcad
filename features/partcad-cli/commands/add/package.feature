@wip @cli @add-package
Feature: `pc add package` command
  As a user
  I want to add an import to a project
  So that I can use the imported package

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # Scenario: Add package with invalid URL
  #   When I run "partcad add invalid-package https://invalid-url.git"
  #   Then the command should exit with a non-zero status code
  #   And STDERR should contain "Invalid repository URL"

  # Scenario: Add duplicate package
  #   Given I have added the OpenVMP-robots package
  #   When I run "partcad add OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
  #   Then the command should exit with a non-zero status code
  #   And STDERR should contain "Package already exists"

  @success @pc-init @pc-install @pc-list
  Scenario: Add and verify package in uninitialized directory
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad add package OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
    Then the command should exit with a status code of "0"
    # And the package structure should be valid
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
        OpenVMP-robots:
          url: https://github.com/openvmp/openvmp-models.git
          type: git
      parts:
      assemblies:
      """
    When I run "partcad install"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "https://github.com/openvmp/openvmp-models.git"
    # And the package should be downloaded successfully
    When I run "partcad list packages"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD packages:"
    And STDOUT should contain "OpenVMP-robots"
    And STDOUT should contain "/OpenVMP-robots/parts"
    And STDOUT should contain "/OpenVMP-robots/robots/don1"
    And STDOUT should not contain "<none>"
    # And STDOUT should match the pattern:
    #   """
    #   PartCAD packages:
    #   - OpenVMP-robots \(git: https://github\.com/openvmp/openvmp-models\.git\)
    #   """
