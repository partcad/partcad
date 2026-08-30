@cli @search @all
Feature: `pc search all` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # Rendering this help imports every module under 'commands/search/', which is
  # what a broken import in one of them takes down: 'search/all.py' annotated
  # 'cli_ctx' with a CliContext it never imported, and 'pc search --help' died
  # with a NameError traceback rather than a click error, because the lazy
  # loader only converts ModuleNotFoundError and SyntaxError.
  Scenario: The search command lists its subcommands
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    When I run "pc search --help"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Search parts by keyword"
    And STDOUT should contain "Search sketches by keyword"
    And STDOUT should contain "Search assemblies by keyword"
    And STDOUT should contain "Search interfaces by keyword"
    And STDOUT should contain "Search packages by keyword"

  Scenario: Search every kind of object at once
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        sketch_01:
          type: basic
          circle: 5
          desc: a basic sketch in PartCAD keyword cube
      parts:
        part_01:
          type: step
          desc: a basic part in PartCAD keyword cube
      assemblies:
        assembly_01:
          type: assy
          desc: a basic assembly in PartCAD keyword cube
      """
    And a file named "part_01.step" with content:
      """
      This is a STEP file for part_01
      """
    And a file named "assembly_01.assy" with content:
      """
      links:
        - part: part_01
      """
    When I run command:
      """
      pc search all -k cube
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "DONE: Search Packages:"
    And STDOUT should contain "DONE: Search Sketches:"
    And STDOUT should contain "DONE: Search Interfaces:"
    And STDOUT should contain "DONE: Search Parts:"
    And STDOUT should contain "DONE: Search Assemblies:"
    And STDOUT should contain "sketch_01"
    And STDOUT should contain "part_01"
    And STDOUT should contain "assembly_01"

  Scenario: Search with no matches
    Given a file named "partcad.yaml" with content:
      """
      parts:
      """
    When I run command:
      """
      pc search all -k cube
      """
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD parts with 'cube' keyword:"
    And STDOUT should contain "PartCAD assemblies with 'cube' keyword:"
    And STDOUT should contain "<none>"
