@cli @pc-open
Feature: `pc open` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @failure @pc-open
  Scenario: An unknown application is refused, and the known ones are named
    # Checked before anything is looked for, so this says the same thing on
    # every machine -- including one that has FreeCAD installed, where the
    # scenarios below must still not open a window.
    When I run "pc --no-ansi open --with solidworks cube.step"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "Unknown application"
    And OUTPUT should contain "freecad"

  @failure @pc-open
  Scenario: A file that is not there is reported rather than opened
    Given a file named "cube.step" does not exist
    When I run "pc --no-ansi open cube.step"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: The reason survives --json, which the editor reads
    # A failure exits non-zero *and* prints the reason as JSON: the message is
    # the whole answer (what to install, how to allow a container), and the
    # VS Code extension's "Open in..." menu has nothing else to show the user.
    Given a file named "cube.step" does not exist
    When I run "pc --no-ansi open --json cube.step"
    Then the command should exit with a non-zero status code
    And STDOUT should contain '"ok": false'
    And STDOUT should contain "No such file"
