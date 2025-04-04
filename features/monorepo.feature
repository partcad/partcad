
@pc
Feature: Handle monorepo paths properly

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """

  @pc-help
  Scenario: Show CLI help
    When I run "mkdir package_a"
    Then the command should exit with a status code of "0"
    When I run "mkdir package_b"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi list packages -r"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "DFRobot"
    When I run "pc --no-ansi list packages -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "DFRobot"
    When I run "pc --help"
    Then the command should exit with a status code of "0"
