@wip @cli @add-part
Feature: Add a part

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
      parts:
      assemblies:
      """    

  @ai-openscad
  Scenario: Add ai-openscad part
    When I run "pc add-part ai-openscad --ai google --desc 'Pixel phone case of a surprising shape' 'generated-case.scad'"
    Then the command should exit with a status code of "0"
    # And a file named "$PWD/partcad.yaml" should have content:
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        generated-case:
          type: ai-openscad
          desc: Pixel phone case of a surprising shape
          provider: google
      assemblies:
      """

  @ai-openscad
  Scenario: Add scad part
    When I run "pc add-part scad test.scad"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        test:
          type: scad
      assemblies:
      """

# TODO: @alexanderilyin: Add Scenarios for pc add-part {cadquery,build123d,step,stl,3mf,ai-cadquery} ...
