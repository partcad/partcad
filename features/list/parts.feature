@cli @list-packages
Feature: `pc list parts` command

  Background: Create temporary environment and initialize project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      import:
        raspberrypi:
          desc: Raspberry Pi
          # TODO-58: @alexanderilyin: Allow 'type: git' to be omitted and auto-detect
          type: git
          url: https://github.com/partcad/partcad-electronics-sbcs-raspberrypi
      """
    # TODO-59: @alexanderilyin: Add case for whole /pub:
    # And a file named "partcad.yaml" does not exist
    # When I run "partcad --no-ansi init"
    # Then the command should exit with a status code of "0"
    # And a file named "partcad.yaml" should be created
    # When I run "partcad --no-ansi install"
    # Then the command should exit with a status code of "0"

  @success @pc-list @pc-list-parts
  Scenario: List parts
    When I run "partcad list parts"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD parts:"
    And STDOUT should contain "Total:"
    And STDOUT should contain "<none>"

  @success @pc-list @pc-list-parts @pc-list-parts-recursively
  Scenario: List parts recursively
    When I run "partcad list parts -r"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD parts:"
    And STDOUT should contain "Total:"
    And STDOUT should not contain "<none>"

  # https://partcad.atlassian.net/browse/PC-163
  # https://github.com/ewels/rich-click/pull/217
  @wip @PC-163 @ewels/rich-click#217  @failure @pc-list @pc-list-parts
  Scenario: List parts with invalid configuration
    Given a file named "partcad.yaml" with content:
      """
      invalid: yaml: content
      """
    When I run "partcad list parts"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Invalid configuration file"
