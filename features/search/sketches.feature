@cli @search @sketches
Feature: `pc search sketches` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Basic search with single sketch matching keyword
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        circle_01:
          type: basic
          desc: The shortest way to create a basic circle in PartCAD
          circle: 5
      """
    When I run command:
      """
      pc search sketches -k circle
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Sketches:"
    Then STDOUT should contain "PartCAD sketches with 'circle' keyword:"
    Then STDOUT should contain "circle_01"
    Then STDOUT should contain "The shortest way to create a basic circle in PartCAD"
    Then STDOUT should contain "Matches: 1"

  Scenario: Search with no matches
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        square_01:
          type: basic
          desc: A simple square shape
          size: 10
      """
    When I run command:
      """
      pc search sketches -k circle
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Sketches:"
    Then STDOUT should contain "PartCAD sketches with 'circle' keyword:"
    Then STDOUT should contain "<none>"

  Scenario: Search with multiple packages
    Given a file named "partcad.yaml" with content:
    """
    sketches:
    """
    Given a directory named "pkg1" exists
    And a file named "pkg1/partcad.yaml" with content:
      """
      sketches:
        circle_01:
          type: basic
          desc: Circle in pkg1
          radius: 10
      """
    Given a directory named "pkg2" exists
    And a file named "pkg2/partcad.yaml" with content:
      """
      sketches:
        circle_02:
          type: basic
          desc: Circle in pkg2
          radius: 15
      """
    When I run command:
      """
      pc search sketches -r -k circle
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Sketches:"
    Then STDOUT should contain "pkg1"
    Then STDOUT should contain "circle_01"
    Then STDOUT should contain "Circle in pkg1"
    Then STDOUT should contain "pkg2"
    Then STDOUT should contain "circle_02"
    Then STDOUT should contain "Circle in pkg2"
    Then STDOUT should contain "Matches: 2"
