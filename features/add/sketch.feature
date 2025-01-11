@cli @add-sketch
Feature: `pc add sketch` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created with content:
      """
      dependencies:
      sketches:
      parts:
      assemblies:
      """

  # TODO(clairbee): add OpenSCAD support for sketches
  # @scad @success
  # Scenario: Add OpenSCAD Part from "example.py" file
  #   Given a file named "test.scad" with content:
  #     """
  #     translate (v= [0,0,0])  cube (size = 10);
  #     """
  #   When I run "partcad add sketch scad test.scad"
  #   Then the command should exit with a status code of "0"
  #   And STDOUT should contain "Adding the part test.scad of type scad"
  #   And STDOUT should contain "DONE: AddSketch: /:"
  #   And a file named "partcad.yaml" should have YAML content:
  #     """
  #     dependencies:
  #     sketches:
  #     parts:
  #       test:
  #         type: scad
  #     assemblies:
  #     """

  # @wip @scad @error
  # Scenario: Reject invalid SCAD syntax
  #   Given a file named "invalid.scad" with content:
  #     """
  #     cube(size = ]);  // Syntax error
  #     """
  #   When I run "partcad add part scad invalid.scad"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid OpenSCAD syntax"

  # @wip @ai-openscad @error
  # Scenario: Handle AI service failure
  #   When I run "partcad add part ai-openscad --ai google --desc 'Simple case' 'case.scad'"
  #   And the AI service is unavailable
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "AI service unavailable"

  # @wip @ai-openscad @error
  # Scenario: Handle invalid AI provider
  #   When I run "partcad add part ai-openscad --ai unknown --desc 'Simple case' 'case.scad'"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid AI provider"

  # @wip @scad @error
  # Scenario: Reject non-existent SCAD file
  #   When I run "partcad add part scad nonexistent.scad"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "File not found"

  # @wip @scad @error
  # Scenario: Reject invalid SCAD syntax
  #   Given a file named "invalid.scad" with content:
  #     """
  #     cube(size = ]);  // Syntax error
  #     """
  #   When I run "partcad add part scad invalid.scad"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid OpenSCAD syntax"

  # @wip @ai-openscad
  # Scenario: Add ai-openscad Part using GoogleAI
  #   When I run "partcad add part ai-openscad --ai google --desc 'Pixel phone case of a surprising shape' 'generated-case.scad'"
  #   Then the command should exit with a status code of "0"
  #   # And a file named "$PWD/partcad.yaml" should have content:
  #   And a file named "partcad.yaml" should have YAML content:
  #     """
  #     dependencies:
  #     sketches:
  #     parts:
  #       generated-case:
  #         type: ai-openscad
  #         desc: Pixel phone case of a surprising shape
  #         provider: google
  #     assemblies:
  #     """

  @cadquery
  Scenario: Add cadquery sketch from "example.py" file
    Given a file named "example.py" with content:
      """
      import cadquery as cq
      result = cq.Workplane("XY").square(1, 2)
      """
    When I run "partcad add sketch cadquery example.py"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
        example:
          type: cadquery
      parts:
      assemblies:
      """

  @build123d
  Scenario: Add build123d sketch from "example.py" file
    Given a file named "example.py" with content:
      """
      from build123d import BuildSketch, Rectangle
      with BuildSketch() as sketch:
        Rectangle(a, b)
      show_object(sketch)
      """
    When I run "partcad add sketch build123d example.py"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
        example:
          type: build123d
      parts:
      assemblies:
      """

  # TODO(clairbee): add support for sketches from STEP files
  # @wip @step
  # Scenario: Add STEP sketch from "sketch.step" file
  #   Given a file named "sketch.step" with content:
  #     """
  #     -- STEP file content --
  #     """
  #   When I run "partcad add sketch step part.step"
  #   Then the command should exit with a status code of "0"
  #   And a file named "partcad.yaml" should have YAML content:
  #     """
  #     dependencies:
  #     sketches:
  #       part:
  #         type: step
  #     parts:
  #     assemblies:
  #     """

  @wip @dxf
  Scenario: Add DXF sketch from "model.dxf" file
    Given a file named "model.dxf" with content:
      """
      0
      SECTION
      1
      ENTITIES
      0
      CIRCLE
      4
      Test
      10
      0.0
      20
      0.0
      30
      0.0
      40
      5.0
      62
      0
      0
      ENDSEC
      0
      EOF
      """
    When I run "partcad add sketch dxf model"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
        model:
          type: dxf
      parts:
      assemblies:
      """

  @wip @svg
  Scenario: Add SVG sketch from "design.svg" file
    Given a file named "design.svg" with content:
      """
      -- SVG file content --
      """
    When I run "partcad add sketch svg design.svg"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      dependencies:
      sketches:
        design:
          type: svg
      parts:
      assemblies:
      """

  # TODO(clairbee): add support for sketches from AI-generated scripts
  # @wip @ai-cadquery
  # Scenario: Add ai-cadquery Part using OpenAI
  #   When I run "partcad add part ai-cadquery --ai openai --desc 'Custom mechanical part' 'custom_part.py'"
  #   Then the command should exit with a status code of "0"
  #   And a file named "partcad.yaml" should have YAML content:
  #     """
  #     dependencies:
  #     sketches:
  #     parts:
  #       custom-part:
  #         type: ai-cadquery
  #         desc: Custom mechanical part
  #         provider: openai
  #     assemblies:
  #     """

  # @wip @cadquery @error
  # Scenario: Reject invalid CadQuery script
  #   Given a file named "invalid_cq.py" with content:
  #     """
  #     import cadquery as cq
  #     result = cq.Workplane("XY").circle(5).extrude()  # Missing extrusion distance
  #     """
  #   When I run "partcad add part cadquery invalid_cq.py"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid CadQuery script"

  # @wip @build123d @error
  # Scenario: Reject invalid Build123D script
  #   Given a file named "invalid_b123d.py" with content:
  #     """
  #     from build123d import *
  #     with BuildPart() as part:
  #         Box(10, 10, 10)
  #         Fillet(edges=part.edges(), radius=2  # Syntax error: missing closing parenthesis
  #     """
  #   When I run "partcad add part build123d invalid_b123d.py"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid Build123D script"

  # TODO(clairbee): add support for sketches from STEP files
  # @wip @step @error
  # Scenario: Reject invalid STEP file
  #   Given a file named "invalid.step" with content:
  #     """
  #     ISO-10303-21;
  #     HEADER;
  #     /* Incomplete STEP file */
  #     ENDSEC;
  #     """
  #   When I run "partcad add part step invalid.step"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Invalid STEP file"

  @wip @dxf @error
  Scenario: Reject invalid DXF file
    Given a file named "invalid.dxf" with content:
      """
      solid InvalidDXF
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      /* Missing 'DXF' content */
      """
    When I run "partcad add sketch dxf invalid.dxf"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid DXF file"

  @wip @svg @error
  Scenario: Reject invalid SVG file
    Given a file named "invalid.svg" with content:
      """
      <?xml version="1.0" encoding="UTF-8"?>
      <model>
        <!-- Corrupted SVG content: missing closing tags -->
      """
    When I run "partcad add sketch svg invalid.svg"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid SVG file"

  # @wip @ai-cadquery @error
  # Scenario: Reject invalid AI-generated CadQuery part
  #   When I run "partcad add part ai-cadquery --ai google --desc 'An impossible object that defies physics' 'impossible.py'"
  #   Then the command should exit with a status code of "1"
  #   And STDERR should contain "Failed to generate CadQuery part"

  # @wip @ai-openscad
  # Scenario: Add scad part from `test.scad` file
  #   # TODO-54: @alexanderilyin: Add scad linting
  #   Given a file named "test.scad" with content:
  #     """
  #     translate (v= [0,0,0])  cube (size = 10);
  #     """
  #   When I run "partcad add part scad test.scad"
  #   Then the command should exit with a status code of "0"
  #   And a file named "partcad.yaml" should have YAML content:
  #     """
  #     dependencies:
  #     sketches:
  #     parts:
  #       test:
  #         type: scad
  #     assemblies:
  #     """
