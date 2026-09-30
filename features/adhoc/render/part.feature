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
