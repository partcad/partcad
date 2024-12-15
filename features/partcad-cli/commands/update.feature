@cli @pc-update
Feature: `pc update` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-update @pc-ansi
  Scenario: Install packages
    Given a file named "partcad.yaml" with content:
      """
      import:
        raspberrypi:
          desc: Raspberry Pi
          # TODO: @alexanderilyin: Allow 'type: git' to be omitted and auto-detect
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
    # TODO: @alexanderilyin: Add output checks
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
