@wip @cli @add-part
Feature: `pc add part` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      import:
      parts:
      assemblies:
      """    

  @ai-openscad
  Scenario: Add ai-openscad Part using GoogleAI
    When I run "partcad add-part ai-openscad --ai google --desc 'Pixel phone case of a surprising shape' 'generated-case.scad'"
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
  Scenario: Add scad part from `test.scad` file
    # TODO: @alexanderilyin: Add scad linting
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    When I run "partcad add-part scad test.scad"
    # TODO: @alexanderilyin: Add validation that 'test.scad' exists
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
