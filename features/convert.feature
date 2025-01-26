@cli @pc-convert
Feature: `pc convert` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" does not exist

  Scenario Outline: `pc convert` command
    When I run "partcad -p /workspaces/partcad/examples convert --package <package> -t <type> -O ./ <object>"
    Then the command should exit with a status code of "0"
    Then a file named "<filename>" should be created
    Then STDOUT should contain "DONE: Convert: this:"
    Then STDOUT should not contain "WARN:"
    Then STDOUT should not contain "ERROR:"

  @part
  Examples: Convert Part
    | package               | object | type    | filename        |
    | /produce_part_stl     | cube   | step    | cube.step       |
    | /produce_part_stl     | cube   | brep    | cube.brep       |
    | /produce_part_stl     | cube   | stl     | cube.stl        |
    | /produce_part_stl     | cube   | threejs | cube.json       |
    | /produce_part_stl     | cube   | gltf    | cube.json       |

  @assembly
  Examples: Convert Assembly
    | package                   | object           | type    | filename              |
    | /produce_assembly_assy    | logo_embedded    | step    | logo_embedded.step    |
    | /produce_assembly_assy    | logo_embedded    | stl     | logo_embedded.stl     |
    | /produce_assembly_assy    | logo_embedded    | obj     | logo_embedded.obj     |

  @sketch
  Examples: Convert Sketch
    | package                | object     | type    | filename          |
    | /produce_sketch_basic  | circle_01  | svg     | circle_01.svg     |
    | /produce_sketch_basic  | rect_01    | svg     | rect_01.svg       |
    | /produce_sketch_svg    | svg_01     | svg     | svg_01.svg        |

---

### Feature: `pc convert` In-Place Updates

@cli @pc-convert-in-place
Feature: `pc convert` command with `--in-place`

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: stl
      """

  Scenario Outline: Convert and update type in partcad.yaml
    When I run "partcad -p /workspaces/partcad/examples convert -t <type> --in-place <object>"
    Then the command should exit with a status code of "0"
    Then a file named "<filename>" should be created
    Then STDOUT should contain "DONE: Convert: this:"
    Then STDOUT should not contain "WARN:"
    Then the `partcad.yaml` file should contain:
      """
      parts:
        cube:
          type: <type>
      """

  @type-object
  Examples: In-Place Conversion
    | type    | object | filename    |
    | step    | cube   | cube.step   |
    | stl     | cube   | cube.stl    |

---

### Feature: Error Handling for `pc convert`

```gherkin
@cli @pc-convert-errors
Feature: `pc convert` error handling

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: stl
      """

  @error
  Scenario: Convert non-existent object
    When I run "partcad convert -t step non_existent_object"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Object 'non_existent_object' not found in parts, assemblies, or sketches"

  @error
  Scenario: Convert with unsupported format
    When I run "partcad convert -t unsupported_format cube"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid choice: 'unsupported_format'"

  @error
  Scenario: Convert without specifying object
    When I run "partcad convert -t step"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Object must be specified for conversion"

---

### Feature: Recursive Package Conversion

```gherkin
@cli @pc-convert-recursive
Feature: `pc convert` command with recursive packages

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given the following files exist:
      """
      /workspaces/partcad/examples/produce_part_recursive/partcad.yaml:
      parts:
        cube_1:
          type: stl
        cube_2:
          type: stl
        cube_3:
          type: stl
      """

  Scenario: Convert all parts in a recursive package
    When I run "partcad -p /workspaces/partcad/examples/produce_part_recursive convert -r -t step"
    Then the command should exit with a status code of "0"
    Then the following files should be created:
      | cube_1.step |
      | cube_2.step |
      | cube_3.step |
    Then STDOUT should contain "DONE: Convert: this:"
    Then STDOUT should not contain "WARN:"
    Then STDOUT should not contain "ERROR:"
