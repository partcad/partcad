@cli @search @interfaces
Feature: `pc search interfaces` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Basic search with single interface matching keyword
    Given a file named "partcad.yaml" with content:
      """
        sketches:
          m3:
            type: basic
            circle: 1.5
        interfaces:
          m3:
            desc: Abstract 3mm circular interface
            abstract: True
            ports:
              m3:
                location: [[0, 0, 0], [0, 0, 1], 0]
                sketch: m3
      """
    When I run command:
      """
      pc search interfaces -k circular
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Interfaces:"
    Then STDOUT should contain "PartCAD interfaces with 'circular' keyword:"
    Then STDOUT should contain "m3"
    Then STDOUT should contain "Abstract 3mm circular interface"
    Then STDOUT should contain "Matches: 1"

  Scenario: Search with no matches
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
      """
    When I run command:
      """
      pc search interfaces -k m3
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Interfaces:"
    Then STDOUT should contain "PartCAD interfaces with 'm3' keyword:"
    Then STDOUT should contain "<none>"

  Scenario: Search within multiple packages
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
      """
    Given a directory named "pkg1" exists
    And a file named "pkg1/partcad.yaml" with content:
      """
      sketches:
        m3_1:
          type: basic
          circle: 1.5
      interfaces:
        m3_1:
          desc: 3mm circular interface in pkg1
          abstract: True
          ports:
            m3_1:
              location: [[0, 0, 0], [0, 0, 1], 0]
              sketch: m3_1
      """
    Given a directory named "pkg2" exists
    And a file named "pkg2/partcad.yaml" with content:
      """
      sketches:
        m3_2:
          type: basic
          circle: 1.5
      interfaces:
        m3_2:
          desc: 3mm circular interface in pkg2
          abstract: True
          ports:
            m3_2:
              location: [[0, 0, 0], [0, 0, 1], 0]
              sketch: m3_2
      """
    When I run command:
      """
      pc search interfaces -r -k circular
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Interfaces:"
    Then STDOUT should contain "pkg1"
    Then STDOUT should contain "m3_1"
    Then STDOUT should contain "3mm circular interface in pkg1"
    Then STDOUT should contain "pkg2"
    Then STDOUT should contain "m3_2"
    Then STDOUT should contain "3mm circular interface in pkg2"
    Then STDOUT should contain "Matches: 2"
