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

  @success @windows-registry
  Scenario: Running health check with all registry checks passing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "0"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabledCheck: Passed"
    Then STDOUT should contain "NoDefaultCurrentDirectoryCheck: Passed"

  @failure @windows-registry
  Scenario: Running health check with LongPathsEnabled failing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "0"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "0"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled is not set to 1"
    Then STDOUT should contain "NoDefaultCurrentDirectoryCheck: Passed"

  @failure @windows-registry
  Scenario: Running health check with "NoDefaultCurrentDirectoryInExePath" failing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "1"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabledCheck: Passed"
    Then STDOUT should contain "NoDefaultCurrentDirectoryInExePath is not set to 0"

  @failure @windows-registry
  Scenario: Running health check with both registry checks failing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "0"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "1"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled is not set to 1"
    Then STDOUT should contain "NoDefaultCurrentDirectoryInExePath is not set to 0"

  @failure @windows-registry
  Scenario: Running health check with "LongPathsEnabled" missing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is missing
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled registry key not found"

  @failure @windows-registry
  Scenario: Running health check with "NoDefaultCurrentDirectoryInExePath" missing
    Given the system is running on Windows
    And "NoDefaultCurrentDirectoryInExePath" registry key is missing
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "NoDefaultCurrentDirectoryInExePath registry key not found"

  @success @windows-registry
  Scenario: Fixing LongPathsEnabledCheck issue
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "0"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "0"
    When I run partcad healthcheck fix
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled is not set to 1"
    Then STDOUT should contain "Auto fix successful"

  @success @windows-registry
  Scenario: Fixing NoDefaultCurrentDirectoryCheck issue
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "1"
    When I run partcad healthcheck fix
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "NoDefaultCurrentDirectoryInExePath is not set to 0"
    Then STDOUT should contain "Auto fix successful"
