@cli @install-packages
Feature: `pc install` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-init @pc-install @pc-ansi
  Scenario: Install packages
    # TODO-55: Check if pc is using shallow cloning with --depth 1
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        raspberrypi:
          desc: Raspberry Pi
          # TODO-56: @alexanderilyin: Allow 'type: git' to be omitted and auto-detect
          type: git
          url: https://github.com/partcad/partcad-electronics-sbcs-raspberrypi
      """
    # TODO-57: @alexanderilyin: Consider to move "partcad/partcad.git:examples" to "partcad/partcad-examples.git". Now clone takes 62.776s
    When I run "partcad install"
    Then STDOUT should contain "Cloning the GIT repo:"
    Then STDOUT should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"


  @wip @success @pc-init @pc-install @pc-ansi
# PC-82: Gracefully handle git & network problems in 'pc update'
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

  @wip @success @pc-init @pc-install @pc-ansi
  Scenario: Install packages with ssh
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        raspberrypi:
          desc: Raspberry Pi
          type: git
          url: https://github.com/partcad/partcad-electronics-sbcs-raspberrypi
      """
    And a user configuration file named "config.yaml" with content:
      """
      dependencies:
        overrides:
          url:
            "git@github.com:": "https://github.com/"
      """
    When I run "partcad install"
    Then STDOUT should contain "Cloning the GIT repo:"
    Then STDOUT should contain "git@github.com:"
    Then STDOUT should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"

  @success @pc-init @pc-install @pc-ansi
  Scenario: Override git configuration
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        raspberrypi:
          desc: Raspberry Pi
          type: git
          url: https://github.com/partcad/partcad-electronics-sbcs-raspberrypi
      """
    And a user configuration file named "config.yaml" with content:
      """
      git:
        config:
          "user.name": "John Doe"
          "user.email": "johndoe@example.com"
      """
    When I run "partcad install"
    Then STDOUT should contain "Cloning the GIT repo:"
    Then STDOUT should contain "DONE: Install: this:"
    Then the command should exit with a status code of "0"
    When I run "git -C ~/.partcad/git/*/ config --get user.name"
    Then STDOUT should contain "John Doe"
    When I run "git -C ~/.partcad/git/*/ config --get user.email"
    Then STDOUT should contain "johndoe@example.com"

  @wip @failure @pc-install
  Scenario: Install non-existent package
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    When I run "partcad install non-existent-package"
    Then the command should exit with a non-zero status code
    And STDERR should contain "Package not found"

  @wip @failure @pc-install
  Scenario: Install with dependency resolution failure
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    When I run "partcad install package-with-conflicts"
    Then the command should exit with a non-zero status code
    And STDERR should contain "Dependency resolution failed"
