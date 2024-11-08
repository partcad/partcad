@cli @list-packages
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
    # TODO: @alexanderilyin: Add output checks
    # Then STDERR should contain "Cloning the GIT repo:"
    # Then STDERR should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"
    
    
