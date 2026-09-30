@cli @pc-adhoc-render @sketch
Feature: `pc adhoc render sketch` command

  The sketch half of `pc adhoc render`. A sketch is already flat, so rendering
  one is a drawing of it rather than a projection through it -- and `svg` and
  `dxf` therefore appear on both sides of this command, meaning the sketch
  itself as an input and a picture of it as an output.

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Render a bare SVG sketch to a PNG
    When I run "pc --no-ansi adhoc render sketch $PARTCAD_ROOT/examples/produce_sketch_svg/svg_01.svg ./sketch.png"
    Then the command should exit with a status code of "0"
    Then a file named "sketch.png" should be created
    Then a file named "partcad.yaml" should not exist

  Scenario: Fail on an output type that is not a projection
    When I run "pc --no-ansi adhoc render sketch $PARTCAD_ROOT/examples/produce_sketch_svg/svg_01.svg ./sketch.py --output cadquery"
    Then the command should exit with a status code of "2"
    Then a file named "sketch.py" should not exist
