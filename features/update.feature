@cli @pc-update
Feature: `pc update` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-update
  Scenario: Report whether a newer PartCAD is available, without installing it
    # `--check` never installs and never stops a daemon, so it is safe to run
    # against whatever this machine happens to have installed. What it prints
    # depends on that (up to date / an update is available / a source checkout,
    # which is what a checkout running from the repository reports), so the
    # assertion is on the shape all three share.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi update --check"
    Then the command should exit with a status code of "0"
    And STDOUT should match the regex "PartCAD \d+\.\d+\.\d+"

  @success @pc-update
  Scenario: Skip the version check in offline mode
    Given a file named "partcad.yaml" does not exist
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi --offline update --check"
    Then STDOUT should contain "Offline mode"
    And the command should exit with a status code of "0"

  @failure @pc-update
  Scenario: Refuse to update PartCAD only and the packages only at once
    When I run "pc --no-ansi update --partcad-only --packages-only"
    Then the command should exit with a non-zero status code

  @success @pc-update @pc-ansi
  Scenario: Install packages
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        raspberrypi:
          desc: Raspberry Pi
          # TODO-81: @alexanderilyin: Allow 'type: git' to be omitted and auto-detect
          type: git
          url: https://github.com/partcad/partcad-electronics-sbcs-raspberrypi
      """
    When I run "partcad update"

  @wip @success @pc-init @pc-update @pc-ansi
  Scenario: Update packages
    Given a file named "partcad.yaml" does not exist
    When I run "partcad init"
    Then STDOUT should contain "DONE: InitCtx: /tmp/sandbox/behave"
    Then the command should exit with a status code of "0"
    Then a file named "partcad.yaml" should be created
    When I run "partcad update"
    # TODO-82: @alexanderilyin: Add output checks
    # Then STDERR should contain "Cloning the GIT repo:"
    # Then STDERR should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"

  @wip @failure @pc-update
  Scenario: Update fails due to network error
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    When I run "partcad update" with simulated network failure
    Then the command should exit with a non-zero status code
    And STDERR should contain "Network error"

  @wip @failure @pc-update
  Scenario: Update fails due to version conflict
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And I have a package with version conflict
    When I run "partcad update"
    Then the command should exit with a non-zero status code
    And STDERR should contain "Version conflict detected"
