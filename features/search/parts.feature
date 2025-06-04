@cli @search @parts
Feature: `pc search parts` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Basic search with single part matching keyword
    Given a file named "partcad.yaml" with content:
      """
      parts:
        part_01:
          type: step
          desc: a basic part in PartCAD keyword cube
      """
    And a file named "part_01.step" with content:
      """
      This is a STEP file for part_01
      """
    When I run command:
      """
      pc search parts -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Parts:"
    Then STDOUT should contain "PartCAD parts with 'cube' keyword:"
    Then STDOUT should contain "part_01"
    Then STDOUT should contain "a basic part in PartCAD keyword cube"
    Then STDOUT should contain "Matches: 1"

  Scenario: Search with no matches
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    When I run command:
      """
      pc search parts -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Parts:"
    Then STDOUT should contain "PartCAD parts with 'cube' keyword:"
    Then STDOUT should contain "<none>"

  Scenario: Search within multiple packages
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    Given a directory named "pkg1" exists
    And a file named "pkg1/partcad.yaml" with content:
      """
      parts:
        part_06:
          type: step
          desc: cube in pkg1
      """
    Given a directory named "pkg2" exists
    And a file named "pkg2/partcad.yaml" with content:
      """
      parts:
        part_07:
          type: step
          desc: cube in pkg2
      """
    And a file named "pkg1/part_06.step" with content:
      """
      This is a STEP file for part_06
      """
    And a file named "pkg2/part_07.step" with content:
      """
      This is a STEP file for part_07
      """
    When I run command:
      """
      pc search parts -r -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Parts:"
    Then STDOUT should contain "pkg1"
    Then STDOUT should contain "part_06"
    Then STDOUT should contain "cube in pkg1"
    Then STDOUT should contain "pkg2"
    Then STDOUT should contain "part_07"
    Then STDOUT should contain "cube in pkg2"
    Then STDOUT should contain "Matches: 2"
