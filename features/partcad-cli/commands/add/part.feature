@cli @add-part
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

  @scad @success
  Scenario: Add cadquery Part from "example.py" file
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    When I run "partcad add part scad test.scad"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Adding the part test.scad of type scad"
    And STDOUT should contain "DONE: AddPart: this:"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        test:
          type: scad
      assemblies:
      """

  @wip @scad @error
  Scenario: Reject invalid SCAD syntax
    Given a file named "invalid.scad" with content:
      """
      cube(size = ]);  // Syntax error
      """
    When I run "partcad add part scad invalid.scad"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid OpenSCAD syntax"

  @wip @ai-openscad @error
  Scenario: Handle AI service failure
    When I run "partcad add part ai-openscad --ai google --desc 'Simple case' 'case.scad'"
    And the AI service is unavailable
    Then the command should exit with a status code of "1"
    And STDERR should contain "AI service unavailable"

  @wip @ai-openscad @error
  Scenario: Handle invalid AI provider
    When I run "partcad add part ai-openscad --ai unknown --desc 'Simple case' 'case.scad'"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid AI provider"

  @wip @scad @error
  Scenario: Reject non-existent SCAD file
    When I run "partcad add part scad nonexistent.scad"
    Then the command should exit with a status code of "1"
    And STDERR should contain "File not found"

  @wip @scad @error
  Scenario: Reject invalid SCAD syntax
    Given a file named "invalid.scad" with content:
      """
      cube(size = ]);  // Syntax error
      """
    When I run "partcad add part scad invalid.scad"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid OpenSCAD syntax"

  @wip @ai-openscad
  Scenario: Add ai-openscad Part using GoogleAI
    When I run "partcad add part ai-openscad --ai google --desc 'Pixel phone case of a surprising shape' 'generated-case.scad'"
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

  @wip @cadquery
  Scenario: Add cadquery Part from "example.py" file
    Given a file named "example.py" with content:
      """
      import cadquery as cq
      result = cq.Workplane("XY").box(1, 2, 3)
      """
    When I run "partcad add part cadquery example.py"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        example:
          type: cadquery
      assemblies:
      """

  @wip @build123d
  Scenario: Add build123d Part from "example.py" file
    Given a file named "example.py" with content:
      """
      from build123d import Box
      result = Box(1, 2, 3)
      """
    When I run "partcad add part build123d example.py"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        example:
          type: build123d
      assemblies:
      """

  @wip @step
  Scenario: Add STEP Part from "part.step" file
    Given a file named "part.step" with content:
      """
      -- STEP file content --
      """
    When I run "partcad add part step part.step"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        part:
          type: step
      assemblies:
      """

  @wip @stl
  Scenario: Add STL Part from "model.stl" file
    Given a file named "model.stl" with content:
      """
      solid model
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      endsolid
      """
    When I run "partcad add part stl model.stl"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        model:
          type: stl
      assemblies:
      """

  @wip @3mf
  Scenario: Add 3MF Part from "design.3mf" file
    Given a file named "design.3mf" with content:
      """
      -- 3MF file content --
      """
    When I run "partcad add part 3mf design.3mf"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        design:
          type: 3mf
      assemblies:
      """

  @wip @ai-cadquery
  Scenario: Add ai-cadquery Part using OpenAI
    When I run "partcad add part ai-cadquery --ai openai --desc 'Custom mechanical part' 'custom_part.py'"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      import:
      parts:
        custom-part:
          type: ai-cadquery
          desc: Custom mechanical part
          provider: openai
      assemblies:
      """

  @wip @cadquery @error
  Scenario: Reject invalid CadQuery script
    Given a file named "invalid_cq.py" with content:
      """
      import cadquery as cq
      result = cq.Workplane("XY").circle(5).extrude()  # Missing extrusion distance
      """
    When I run "partcad add part cadquery invalid_cq.py"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid CadQuery script"

  @wip @build123d @error
  Scenario: Reject invalid Build123D script
    Given a file named "invalid_b123d.py" with content:
      """
      from build123d import *
      with BuildPart() as part:
          Box(10, 10, 10)
          Fillet(edges=part.edges(), radius=2  # Syntax error: missing closing parenthesis
      """
    When I run "partcad add part build123d invalid_b123d.py"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid Build123D script"

  @wip @step @error
  Scenario: Reject invalid STEP file
    Given a file named "invalid.step" with content:
      """
      ISO-10303-21;
      HEADER;
      /* Incomplete STEP file */
      ENDSEC;
      """
    When I run "partcad add part step invalid.step"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid STEP file"

  @wip @stl @error
  Scenario: Reject invalid STL file
    Given a file named "invalid.stl" with content:
      """
      solid InvalidSTL
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      /* Missing 'endsolid' keyword */
      """
    When I run "partcad add part stl invalid.stl"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid STL file"

  @wip @3mf @error
  Scenario: Reject invalid 3MF file
    Given a file named "invalid.3mf" with content:
      """
      <?xml version="1.0" encoding="UTF-8"?>
      <model>
        <!-- Corrupted 3MF content: missing closing tags -->
      """
    When I run "partcad add part 3mf invalid.3mf"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid 3MF file"

  @wip @ai-cadquery @error
  Scenario: Reject invalid AI-generated CadQuery part
    When I run "partcad add part ai-cadquery --ai google --desc 'An impossible object that defies physics' 'impossible.py'"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Failed to generate CadQuery part"

  @wip @ai-openscad
  Scenario: Add scad part from `test.scad` file
    # TODO: @alexanderilyin: Add scad linting
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    When I run "partcad add part scad test.scad"
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
