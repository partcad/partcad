@cli @pc-healthcheck
Feature: 'pc healthcheck' command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @failure @python-version
  Scenario: Running health check with an invalid version
    Given system python version is "3.7"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Python version 3.7 is not supported"

  @success @python-version
  Scenario: Running health check with a valid version
    Given system python version is "3.11"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "PythonVersion: Passed"

  @failure @python-version
  Scenario: Running health check with a invalid version
    Given system python version is "3.13"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Python version 3.13 is not supported"

  @failure @python-version
  Scenario: Running health check fix with an invalid version
    Given system python version is "3.13"
    When I run partcad healthcheck fix
    Then the command should exit with a status code of "1"
    Then STDOUT should contain "Auto fix failed"
