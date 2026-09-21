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

  # Not by what the declaration says but by what the part connects by: the
  # interface it implements, or anything that interface is derived from.
  Scenario: Search by interface
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
        m3:
          abstract: true
          ports:
            m3:
        m3-thru:
          inherits:
            m3: thru
      parts:
        plate:
          type: step
          desc: a plate with a 3mm through hole
          implements:
            m3-thru: [[0, 0, 0], [0, 0, 1], 0]
        block:
          type: step
          desc: a block with nothing to connect to
      """
    And a file named "plate.step" with content:
      """
      This is a STEP file for plate
      """
    And a file named "block.step" with content:
      """
      This is a STEP file for block
      """
    When I run command:
      """
      pc search parts -i m3-thru
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "PartCAD parts implementing 'm3-thru':"
    Then STDOUT should contain "a plate with a 3mm through hole"
    Then STDOUT should not contain "a block with nothing to connect to"
    Then STDOUT should contain "Matches: 1"

  # The abstract interface a family derives from is the name that family is
  # known by, so searching for it finds what implements anything below it.
  Scenario: Search by the interface a part's interface is derived from
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
        m3:
          abstract: true
          ports:
            m3:
        m3-thru:
          inherits:
            m3: thru
      parts:
        plate:
          type: step
          desc: a plate with a 3mm through hole
          implements:
            m3-thru: [[0, 0, 0], [0, 0, 1], 0]
      """
    And a file named "plate.step" with content:
      """
      This is a STEP file for plate
      """
    When I run command:
      """
      pc search parts -i m3
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "plate"
    Then STDOUT should contain "Matches: 1"

  Scenario: Searching for nothing at all is a usage error
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    When I run command:
      """
      pc search parts
      """
    Then the command should exit with a status code of "2"
    Then STDERR should contain "Nothing to search for"
