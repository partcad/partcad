@cli @pc-ai-regenerate
Feature: `pc ai regenerate` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-ai-regenerate
  Scenario: `pc ai regenerate` without an object reports a clear error without crashing
    Given a file named "partcad.yaml" with content:
      """
      desc: A sample PartCAD package
      """
    When I run "pc ai regenerate"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "No object specified"
    And STDERR should not contain "Traceback"
