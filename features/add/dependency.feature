@cli @add-dependency
Feature: `pc add dep` command
  As a user
  I want to add a dependency entry to the current project
  So that I can make references (e.g. in assemblies) to objects in the target project and its dependencies

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # Scenario: Add a dependency with invalid URL
  #   When I run "partcad add invalid-dependency https://invalid-url.git"
  #   Then the command should exit with a non-zero status code
  #   And STDERR should contain "Invalid repository URL"

  # Scenario: Add duplicate dependency
  #   Given I have added the OpenVMP-robots dependency
  #   When I run "partcad add OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
  #   Then the command should exit with a non-zero status code
  #   And STDERR should contain "Dependency already exists"

  @success @pc-init @pc-install @pc-list
  Scenario: Add and verify dependency in uninitialized directory
    Given a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad add dep OpenVMP-robots https://github.com/openvmp/openvmp-models.git"
    Then the command should exit with a status code of "0"
    # And the package structure should be valid
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      pythonVersion: ">=\\d+\\.\\d+"
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
        OpenVMP-robots:
          url: https://github.com/openvmp/openvmp-models.git
          type: git
      sketches:
      parts:
      assemblies:
      """
    When I run "partcad install"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "https://github.com/openvmp/openvmp-models.git"
    # And the package should be downloaded successfully
    # And the directory "OpenVMP-robots" should exist
    # And the file "OpenVMP-robots/package.yaml" should exist
    # And the directory "OpenVMP-robots/.git" should exist
    # And STDOUT should contain "Successfully installed OpenVMP-robots"

    When I run "partcad list packages -r"
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

# And the directory "OpenVMP-robots" should exist
# And the file "OpenVMP-robots/package.yaml" should exist
# And the file "OpenVMP-robots/package.yaml" should have YAML content:
#   """
#   name: OpenVMP-robots
#   version: 1.0.0
#   """
