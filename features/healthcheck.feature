@cli @pc-healthcheck
Feature: 'pc healthcheck' command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # The four bounds of `requires-python` in `pyproject.toml` (">=3.10,<3.15"),
  # one scenario each. 3.13 used to be here as an *unsupported* version, which
  # is what the check said and `pyproject.toml` had not said for some time.
  @failure @python-version
  Scenario: Running health check on a version older than the minimum
    Given system python version is "3.7"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Python version 3.7 is not supported"

  @success @python-version
  Scenario: Running health check on a supported version
    Given system python version is "3.11"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "PythonVersion: Passed"

  # The interpreter the standalone bundle carries. While the check stopped at
  # 3.12, the bundle spent every start reporting that the Python it ships is
  # unsupported and telling the user to change a system Python it does not use.
  @success @python-version
  Scenario: Running health check on the newest supported version
    Given system python version is "3.14"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "PythonVersion: Passed"

  @failure @python-version
  Scenario: Running health check on a version newer than the maximum
    Given system python version is "3.15"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Python version 3.15 is not supported"

  @success @python-version @filters
  Scenario: Run healthcheck command with dry run and filter
    When I run partcad healthcheck with options "--dry-run --filters=python"
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Suggested healthcheck: PythonVersion - "
    Then STDOUT should not contain "Suggested healthcheck: LongPathsEnabledCheck - "
    Then STDOUT should not contain "Suggested healthcheck: NoDefaultCurrentDirectoryCheck - "

  @success @windows-registry @filters
  Scenario: Run healthcheck command with dry run and filter
    Given the system is running on Windows
    When I run partcad healthcheck with options "--dry-run --filters=windows"
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Suggested healthcheck: LongPathsEnabledCheck - "
    Then STDOUT should contain "Suggested healthcheck: NoDefaultCurrentDirectoryCheck - "
    Then STDOUT should not contain "Suggested healthcheck: PythonVersion - "

  @success @windows-registry
  Scenario: Running health check with all registry checks passing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "0"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Healthcheck: LongPathsEnabledCheck: Passed"
    Then STDOUT should contain "Healthcheck: NoDefaultCurrentDirectoryCheck: Passed"

  @failure @windows-registry
  Scenario: Running health check with LongPathsEnabled failing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "0"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "0"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled is not set to 1"
    Then STDOUT should contain "Healthcheck: NoDefaultCurrentDirectoryCheck: Passed"

  @failure @windows-registry
  Scenario: Running health check with "NoDefaultCurrentDirectoryInExePath" failing
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "1"
    When I run partcad healthcheck
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "Healthcheck: LongPathsEnabledCheck: Passed"
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
    When I run partcad healthcheck with options "--fix"
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "LongPathsEnabled is not set to 1"
    Then STDOUT should contain "Auto fix successful"

  @success @windows-registry
  Scenario: Fixing NoDefaultCurrentDirectoryCheck issue
    Given the system is running on Windows
    And "LongPathsEnabled" registry key is set to "1"
    And "NoDefaultCurrentDirectoryInExePath" registry key is set to "1"
    When I run partcad healthcheck with options "--fix"
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "NoDefaultCurrentDirectoryInExePath is not set to 0"
    Then STDOUT should contain "Auto fix successful"
