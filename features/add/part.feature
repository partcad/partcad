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
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      """

  @scad @success
  Scenario: Add OpenSCAD Part from "example.scad" file
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    When I run "partcad add part scad test.scad"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Adding the part test.scad of type scad"
    And STDOUT should contain "DONE: AddPart: //"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
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

  @cadquery
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
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        example:
          type: cadquery
      assemblies:
      """

  @build123d
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
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        example:
          type: build123d
      assemblies:
      """

  @sdf
  Scenario: Add sdf Part from "example.py" file
    Given a file named "example.py" with content:
      """
      from sdf import *
      f = box((1, 1, 1))
      """
    When I run "partcad add part sdf example.py"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        example:
          type: sdf
      assemblies:
      """

  @step
  Scenario: Add STEP Part from "part.step" file
    Given a file named "part.step" with content:
      """
      -- STEP file content --
      """
    When I run "partcad add part step part.step"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        part:
          type: step
      assemblies:
      """

  @stl
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
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        model:
          type: stl
      assemblies:
      """

  @3mf
  Scenario: Add 3MF Part from "design.3mf" file
    Given a file named "design.3mf" with content:
      """
      -- 3MF file content --
      """
    When I run "partcad add part 3mf design.3mf"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        design:
          type: 3mf
      assemblies:
      """

  # The part types PartCAD ships as declarations in '//builtin/import' rather
  # than as factories. Adding one writes its declaration and reads nothing, so
  # these files are placeholders, never built: PartCAD has no SolidWorks,
  # Inventor, CATIA, ACIS or Creo View file it may redistribute, and the ones it
  # has are built below.
  @native
  Scenario Outline: Add a <kind> part from a file named as its type is
    Given a file named "<file>" with content:
      """
      placeholder: never read, this part is not built
      """
    When I run "partcad add part <kind> <file>"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Part '<name>' added to the project."
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        <name>:
          type: <kind>
      assemblies:
      """

    Examples:
      | kind    | file              | name     |
      | fcstd   | design.FCStd      | design   |
      | f3d     | design.f3d        | design   |
      | sldprt  | bracket.SLDPRT    | bracket  |
      | ipt     | bracket.ipt       | bracket  |
      | catpart | bracket.CATPart   | bracket  |
      | sat     | body.sat          | body     |
      | pvz     | product.pvz       | product  |
      | iges    | plate.iges        | plate    |

  # Another spelling of the extension, or another case of it: the part is still
  # named after the file, and its 'path' says which file that is, because the
  # one it would be looked for at otherwise is '<name>.<declared extension>'.
  @native
  Scenario Outline: Add a <kind> part from a file in another spelling of its extension
    Given a file named "<file>" with content:
      """
      placeholder: never read, this part is not built
      """
    When I run "partcad add part <kind> <file>"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Part '<name>' added to the project."
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        <name>:
          type: <kind>
          path: <file>
      assemblies:
      """

    Examples:
      | kind    | file              | name     |
      | iges    | plate.igs         | plate    |
      | sat     | body.sab          | body     |
      | sat     | body.smt          | body     |
      | sat     | body.smb          | body     |
      | fcstd   | design.fcstd      | design   |
      | sldprt  | bracket.sldprt    | bracket  |
      | catpart | bracket.catpart   | bracket  |
      | step    | part.stp          | part     |

  @native
  Scenario: Reject a native part type PartCAD does not have
    Given a file named "design.3dm" with content:
      """
      placeholder
      """
    When I run "partcad add part 3dm design.3dm"
    Then the command should exit with a status code of "2"
    And STDERR should contain "'3dm' is not one of"

  # What was added is what gets built: the Fusion design and the FreeCAD
  # document in the tree both read into solids.
  @native @f3d @fcstd
  Scenario: A native part added from a file builds
    Given I copy file "tests/partcad/unit/data/import_cadmpeg/controller.f3d" to "controller.f3d" inside test workspace
    And I copy file "tests/partcad/unit/data/import_fcstd/design_history.FCStd" to "design_history.FCStd" inside test workspace
    When I run "partcad add part f3d controller.f3d"
    Then the command should exit with a status code of "0"
    When I run "partcad add part fcstd design_history.FCStd"
    Then the command should exit with a status code of "0"
    When I run "partcad --no-ansi export -t step :controller"
    Then the command should exit with a status code of "0"
    And a file named "controller.step" should exist
    When I run "partcad --no-ansi export -t step :design_history"
    Then the command should exit with a status code of "0"
    And a file named "design_history.step" should exist

  # As with STEP, adding a file does not read it -- so a file that holds no
  # solid is added, and fails when it is built. Every one of these types
  # requires a solid, so a read that comes back with loose faces fails too.
  @native @iges @f3d @error
  Scenario: A native part that does not read into a solid fails to build
    Given I copy file "tests/partcad/unit/data/import_cadmpeg/plate.igs" to "plate.igs" inside test workspace
    And a file named "broken.f3d" with content:
      """
      not a Fusion design
      """
    When I run "partcad add part iges plate.igs"
    Then the command should exit with a status code of "0"
    When I run "partcad add part f3d broken.f3d"
    Then the command should exit with a status code of "0"
    When I run "partcad --no-ansi export -t step :plate"
    Then the command should exit with a non-zero status code
    And STDERR should contain "plate is not a solid"
    And a file named "plate.step" should not exist
    When I run "partcad --no-ansi export -t step :broken"
    Then the command should exit with a non-zero status code
    And STDERR should contain "unrecognized format"
    And a file named "broken.step" should not exist

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

  @wip @scad
  Scenario: Add scad part from `test.scad` file
    # TODO-54: @alexanderilyin: Add scad linting
    Given a file named "test.scad" with content:
      """
      translate (v= [0,0,0])  cube (size = 10);
      """
    When I run "partcad add part scad test.scad"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
        test:
          type: scad
      assemblies:
      """

@obj
Scenario: Add OBJ Part from "model.obj" file
  Given a file named "model.obj" with content:
    """
    v 0.0 0.0 0.0
    v 1.0 0.0 0.0
    v 0.0 1.0 0.0
    f 1 2 3
    """
  When I run "pc add part obj model.obj"
  Then the command should exit with a status code of "0"
  And a file named "partcad.yaml" should have YAML content:
    """
    private: true
    partcad: ">=\\d+\\.\\d+\\.\\d+"
    dependencies:
    sketches:
    parts:
      model:
        type: obj
    assemblies:
    """

@wip @obj @error
Scenario: Reject invalid OBJ syntax
  Given a file named "invalid.obj" with content:
    """
    v 0.0 0.0 0.0
    v 1.0 0.0 0.0
    f 1 2  # Missing third vertex
    """
  When I run "pc add part obj invalid.obj"
  Then the command should exit with a status code of "1"
  And STDERR should contain "Invalid OBJ syntax"

@wip @obj @error
Scenario: Reject non-existent OBJ file
  When I run "pc add part obj nonexistent.obj"
  Then the command should exit with a status code of "1"
  And STDERR should contain "does not exist."

@wip @obj @error
Scenario: Reject corrupted OBJ file
  Given a file named "corrupt.obj" with content:
    """
    v 0.0 0.0 0.0
    v 1.0 0.0 0.0
    v x y z  # Invalid vertex
    f 1 2 3
    """
  When I run "pc add part obj corrupt.obj"
  Then the command should exit with a status code of "1"
  And STDERR should contain "Invalid OBJ file"
