@cli @pc-compare
Feature: `pc compare` command

  # 'basic' parts are written by PartCAD itself, with no sandbox, so their
  # volumes and masses cost nothing to compare. The surface distance and the
  # displacement do need the sandbox, and are covered by the unit tests of
  # 'wrapper_compare' and 'wrapper_measure' instead.

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: basic
          cuboid: 10
          properties:
            physics:
              density: 2700
        taller:
          type: basic
          cuboid: [10, 10, 10.5]
          properties:
            physics:
              density: 2700
          requirements:
            match:
              :cube:
                volume: 4%
                weight: 6
      """

  @success
  Scenario: The volumes and the masses of two parts are reported, and nothing is judged
    When I run "pc compare cube taller"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "volume: 1000 mm^3 -> 1050 mm^3, difference +50 mm^3 (+5%)"
    And STDOUT should contain "mass: 0.0027 kg -> 0.002835 kg"
    And STDOUT should contain "this is a report, not a verdict"

  @failure
  Scenario: A limit the current part is further from the reference than fails the command
    When I run "pc compare --max-volume-difference 4 cube taller"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "[FAIL: within 4%]"

  @success
  Scenario: The comparison is printed as JSON
    When I run "pc compare --json --max-mass-difference 6 cube taller"
    Then the command should exit with a status code of "0"
    And STDOUT should contain ""passed": true"
    And STDOUT should contain ""percent": 5.0"

  @failure @pc-test
  Scenario: A 'match:' requirement is checked by `pc test`
    When I run "pc test -f requirements taller"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "match: volume of :cube: within 4%"
    And STDOUT should not contain "mass of :cube"
