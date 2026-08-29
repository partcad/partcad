@cli @add-software
Feature: `pc add software` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Add software the package carries
    Given a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "partcad add software firmware.bin --desc 'The controller image'"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Adding the software firmware.bin"
    And STDOUT should contain "Software 'firmware' added to the project."
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      software:
        firmware:
          desc: The controller image
          path: firmware.bin
      """

  @success
  Scenario: The added software is listed
    Given a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "partcad add software firmware.bin"
    Then the command should exit with a status code of "0"
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "firmware"
    And STDOUT should contain "Total: 1"

  @failure
  Scenario: Software that is not there is refused
    When I run "partcad add software nowhere.bin"
    Then the command should exit with a non-zero status code
    # Nothing was written: a usage error leaves the package as it was.
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "<none>"
