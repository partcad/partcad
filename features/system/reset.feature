@cli
Feature: `pc system reset` command

  `pc system ...` acts on the machine the CLI runs on. Its daemon-side
  counterpart is `pc daemon reset`, covered in `features/daemon.feature`.

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-reset @success
  Scenario: Reset everything
    When I run "partcad --no-ansi system reset"
    Then the command should exit with a status code of "0"
    And STDERR should contain "DONE: Reset: global:"

  @pc-reset @success
  Scenario Outline: Reset one kind of internal data
    When I run "partcad --no-ansi system reset <option>"
    Then the command should exit with a status code of "0"
    And STDERR should contain "DONE: Reset: global:"

    Examples:
      | option         |
      | --repo-only    |
      | --sandbox-only |
      | --cache-only   |

  @pc-reset @success
  Scenario: Resetting is safe to repeat when there is nothing left to remove
    When I run "partcad --no-ansi system reset"
    Then the command should exit with a status code of "0"
    When I run "partcad --no-ansi system reset"
    Then the command should exit with a status code of "0"
    And STDERR should contain "DONE: Reset: global:"

  @pc-reset @pc-status @success
  Scenario: The internal storage is empty after a reset
    When I run "partcad --no-ansi system reset"
    Then the command should exit with a status code of "0"
    When I run "partcad --no-ansi system status"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Git cache size: 0.00MB"
    And STDERR should contain "Tar cache size: 0.00MB"
    # The package cache the bundled conda fills goes with the sandboxes it built
    # -- a reset that left gigabytes of packages behind would not have reset much.
    And STDERR should contain "Conda package cache size: 0.00MB"
