@cli @pc-adhoc-render @part
Feature: `pc adhoc render part` command

  Renders a CAD file that belongs to no package. The projection itself is the
  same one `pc render` writes and is covered there; what these scenarios are for
  is the ad-hoc half -- that a bare file can be rendered at all, that the
  viewport reaches it, and that a request which cannot be carried out is refused
  rather than half-done.

  The input is an example checked into this repository rather than a file
  written inline: what is being rendered is not the subject, and a STEP known to
  render keeps a failure here pointing at this command.

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Render a bare STEP file to a PNG from a named view
    When I run "pc --no-ansi adhoc render part --view top $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.png"
    Then the command should exit with a status code of "0"
    Then a file named "bolt.png" should be created
    # Nothing was added to any package, which is the whole point of `adhoc`.
    Then a file named "partcad.yaml" should not exist

  Scenario: Fail on a projection PartCAD does not write
    When I run "pc --no-ansi adhoc render part $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.tiff --output tiff"
    Then the command should exit with a status code of "2"
    Then a file named "bolt.tiff" should not exist

  Scenario: Fail when the output names a part type rather than a projection
    When I run "pc --no-ansi adhoc render part $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.stl"
    Then the command should exit with a status code of "1"
    Then STDERR should contain "Cannot infer the projection to render"
    Then a file named "bolt.stl" should not exist

  Scenario Outline: Fail on a viewport that cannot be made sense of
    When I run "pc --no-ansi adhoc render part <options> $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.png"
    Then the command should exit with a status code of "2"
    Then a file named "bolt.png" should not exist

    Examples: Bad viewports
      |                    options |
      |          --view isometric  |
      |      --viewport-origin 1,2 |
      |        --viewport-up 0,0,0 |

  Scenario: Fail when the input file is missing
    When I run "pc --no-ansi adhoc render part missing.step ./missing.png"
    Then the command should exit with a status code of "2"

  # What `pc adhoc render` takes that `pc render` takes, for a script that is in
  # no package: a value of one of its parameters, the hidden-line algorithm, and
  # a directory to write into, under the input's name and its values. A cylinder
  # seen end on is the one shape whose drawing says which algorithm drew it: the
  # exact one writes its outline as a circle, the polygonal one as segments.
  @type-image
  Scenario: Render a script with a value of its parameter, both ways, into a directory
    Given a file named "disc.py" with content:
      """
      radius = 5

      from build123d import Cylinder

      show_object(Cylinder(radius, 2))
      """
    Given a directory named "exact" exists
    Given a directory named "polygonal" exists
    When I run "pc --no-ansi adhoc render part --input build123d -p radius=8 --reproducible --view top -t svg -O exact disc.py"
    Then the command should exit with a status code of "0"
    Then a file named "exact/disc_radius_8.svg" should contain "<circle"
    When I run "pc --no-ansi adhoc render part --input build123d -p radius=8 --no-reproducible --view top -t svg -O polygonal disc.py"
    Then the command should exit with a status code of "0"
    Then a file named "polygonal/disc_radius_8.svg" should not contain "<circle"
    Then a file named "partcad.yaml" should not exist

  # `-e` names a package to read the file type from. With no workspace around
  # the file, that is one in the public index or a package directory, which the
  # throwaway package imports -- and the file is named with the extension that
  # package's declaration gives it.
  @type-image
  Scenario: Render to a file type a package directory declares
    Given a directory named "drawing" exists
    Given a file named "drawing/partcad.yaml" with content:
      """
      render:
        svg-thin:
          package: //builtin/render
          path: render_svg.py
          extension: thin.svg
          line_weight: 0.2
      """
    When I run "pc --no-ansi adhoc render part -e drawing -t svg-thin -O . $PARTCAD_ROOT/examples/produce_part_step/bolt.step"
    Then the command should exit with a status code of "0"
    Then a file named "bolt.thin.svg" should be created

  # Refused before anything is built.
  Scenario: Fail on a file type the package it is read from does not declare
    Given a directory named "drawing" exists
    Given a file named "drawing/partcad.yaml" with content:
      """
      render:
        svg-thin:
          package: //builtin/render
          path: render_svg.py
          extension: thin.svg
      """
    When I run "pc --no-ansi adhoc render part -e drawing -t nosuch $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.svg"
    Then the command should exit with a status code of "2"
    Then STDERR should contain "declares no 'nosuch' file type"
    Then a file named "bolt.svg" should not exist

  Scenario: Fail on a package an ad-hoc render cannot reach
    When I run "pc --no-ansi adhoc render part -e nowhere -t svg $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.svg"
    Then the command should exit with a status code of "2"
    Then a file named "bolt.svg" should not exist

  Scenario: Fail when told both the output file and the directory to write it into
    When I run "pc --no-ansi adhoc render part -O . $PARTCAD_ROOT/examples/produce_part_step/bolt.step ./bolt.png"
    Then the command should exit with a status code of "2"
    Then a file named "bolt.png" should not exist
