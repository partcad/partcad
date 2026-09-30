@cli @list-software
Feature: `pc list software` command

  Background: Create temporary environment and a package that ships software
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      desc: A package that ships software

      software:
        controller-firmware:
          desc: The image the controller board is flashed with
          version: "1.0.0"
          path: controller-firmware.bin
        service-tool: service-tool.sh
      """
    And a file named "controller-firmware.bin" with content:
      """
      PARTCAD-EXAMPLE-FIRMWARE
      """
    And a file named "service-tool.sh" with content:
      """
      #!/bin/sh
      echo "the tool the device ships with"
      """

  @success @pc-list @pc-list-software
  Scenario: List software
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD software:"
    And STDOUT should contain "controller-firmware"
    And STDOUT should contain "The image the controller board is flashed with"
    And STDOUT should contain "service-tool"
    And STDOUT should contain "Total: 2"

  @success @pc-list @pc-list-software
  Scenario: A package with no software says so
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with no software at all
      """
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD software:"
    And STDOUT should contain "<none>"
