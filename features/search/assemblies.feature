@cli @search @assemblies
Feature: `pc search assemblies` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Basic search with single assembly matching keyword
    Given a file named "partcad.yaml" with content:
      """
      assemblies:
        assembly_01:
          type: assy
          desc: cube assembly
      """
    And a file named "assembly_01.assy" with content:
      """
      This is an assy file for assembly_01
      """
    When I run command:
      """
      pc search assemblies -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Assemblies:"
    Then STDOUT should contain "PartCAD assemblies with 'cube' keyword:"
    Then STDOUT should contain "assembly_01"
    Then STDOUT should contain "Matches: 1"

  Scenario: Search with no matches
    Given a file named "partcad.yaml" with content:
      """
      assemblies:
      """
    When I run command:
      """
      pc search assemblies -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Assemblies:"
    Then STDOUT should contain "PartCAD assemblies with 'cube' keyword:"
    Then STDOUT should contain "<none>"

  Scenario: Search within multiple packages
    Given a file named "partcad.yaml" with content:
      """
      assemblies:
      """
    Given a directory named "pkg1" exists
    And a file named "pkg1/partcad.yaml" with content:
      """
      assemblies:
        assembly_02:
          type: assy
          desc: assembly with cube in pkg1
      """
    And a file named "pkg1/assembly_02.assy" with content:
      """
      This is an assy file for assembly_02
      """
    Given a directory named "pkg2" exists
    And a file named "pkg2/partcad.yaml" with content:
      """
      assemblies:
        assembly_03:
          type: assy
          desc: assembly with cube in pkg2
      """
    And a file named "pkg2/assembly_03.assy" with content:
      """
      This is an assy file for assembly_03
      """
    When I run command:
      """
      pc search assemblies -r -k cube
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: Search Assemblies:"
    Then STDOUT should contain "pkg1"
    Then STDOUT should contain "assembly_02"
    Then STDOUT should contain "assembly with cube in pkg1"
    Then STDOUT should contain "pkg2"
    Then STDOUT should contain "assembly_03"
    Then STDOUT should contain "assembly with cube in pkg2"
    Then STDOUT should contain "Matches: 2"
