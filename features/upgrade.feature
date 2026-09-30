@cli @pc-upgrade
Feature: `pc upgrade` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-upgrade
  Scenario: Report whether a newer PartCAD is available, without installing it
    # `--check` never installs and never stops a daemon, so it is safe to run
    # against whatever this machine happens to have installed. What it prints
    # depends on that (up to date / an upgrade is available / a source checkout,
    # which is what a checkout running from the repository reports), so the
    # assertion is on the shape all three share.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi upgrade --check"
    Then the command should exit with a status code of "0"
    And STDOUT should match the regex "PartCAD \d+\.\d+\.\d+"

  @success @pc-upgrade
  Scenario: Skip the version check in offline mode
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi --offline upgrade"
    Then STDOUT should contain "Offline mode"
    And the command should exit with a status code of "0"

  @failure @pc-upgrade @pc-update
  Scenario: Upgrading PartCAD is a separate command from updating packages
    # `pc update` refetches a package's imports and takes no upgrade options;
    # upgrading the installation is `pc upgrade`. Keeping them apart is the point
    # of having two commands, so this fails if they are ever merged again.
    When I run "pc --no-ansi update --check"
    Then the command should exit with a non-zero status code
