@cli @install-packages
Feature: `pc install` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-init @pc-install @pc-ansi
  Scenario: Install packages
    Given a file named "partcad.yaml" does not exist
    When I run "partcad init"
    Then STDOUT should contain "DONE: InitCtx: /tmp/sandbox/behave"
    And the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    When I run "partcad install"
    Then STDERR should contain "Cloning the GIT repo:"
    Then STDERR should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"

  @failure @pc-install
  Scenario: Install non-existent package
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    When I run "partcad install non-existent-package"
    Then the command should exit with a non-zero status code
    And STDERR should contain "Package not found"

  @failure @pc-install
  Scenario: Install with dependency resolution failure
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    When I run "partcad install package-with-conflicts"
    Then the command should exit with a non-zero status code
    And STDERR should contain "Dependency resolution failed"
