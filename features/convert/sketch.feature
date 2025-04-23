@cli @convert @sketch
Feature: `pc convert sketch` command

  Background: Initialize PartCAD sketch project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And I copy file "examples/feature_convert_sketch/svg/cylinder.svg" to "cylinder.svg" inside test workspace
    And a file named "partcad.yaml" with content:
      """
      sketches:
        base:
          type: svg
          path: cylinder.svg
        enriched:
          type: enrich
          source: ":base"
        aliased:
          type: alias
          source: ":base"
      """

  Scenario: Dry-run conversion for sketch `base`
    When I run "pc convert sketch base -t dxf --dry-run"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "[Dry Run] No changes made for 'base'."

  Scenario: Conversion with specified output directory for sketch `base`
    Given a directory named "output" exists
    When I run "pc convert sketch base -t dxf -O output"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting sketch"
    And a file named "output/base.dxf" should exist

  Scenario: Missing sketch argument
    When I run "pc convert sketch -t dxf"
    Then the command should exit with a status code of "2"

  Scenario: Conversion failure due to non-existent sketch
    When I run "pc convert sketch nonexisting -t svg"
    Then the command should exit with a status code of "2"

  Scenario: Resolve enrich sketch without specifying target format
    When I run "pc convert sketch enriched"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting sketch"
    And a file named "enriched.svg" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      sketches:
        base:
          type: svg
          path: cylinder.svg

        enriched:
          type: svg
          path: enriched.svg
          manufacturable: True

        aliased:
          type: alias
          source: ":base"
      """

  Scenario: Resolve alias sketch without specifying target format
    When I run "pc convert sketch aliased"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting sketch 'aliased'"
    And a file named "aliased.svg" should exist
    And a file named "partcad.yaml" should have YAML content:
      """
      sketches:
        base:
          type: svg
          path: cylinder.svg

        enriched:
          type: enrich
          source: ":base"

        aliased:
          type: svg
          path: aliased.svg
          manufacturable: True
      """

  Scenario: Enrich sketch conversion to another format
    When I run "pc convert sketch enriched -t dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting sketch 'enriched'"
    And STDOUT should contain "Converting sketch 'enriched'"
    And a file named "enriched.dxf" should exist

  Scenario: Alias sketch conversion to another format
    When I run "pc convert sketch aliased -t dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting sketch 'aliased'"
    And STDOUT should contain "Converting sketch 'aliased'"
    And a file named "aliased.dxf" should exist

  Scenario: Resolve enrich sketch with output directory
    Given a directory named "out" exists
    When I run "pc convert sketch enriched -t dxf -O out"
    Then the command should exit with a status code of "0"
    And a file named "out/enriched.dxf" should exist

  Scenario: Resolve alias sketch with output directory
    Given a directory named "out" exists
    When I run "pc convert sketch aliased -t dxf -O out"
    Then the command should exit with a status code of "0"
    And a file named "out/aliased.dxf" should exist

  Scenario: Failing enrich sketch resolution
    When I run "pc convert sketch missing_enrich"
    Then the command should exit with a status code of "2"

  Scenario: Failing alias sketch resolution
    When I run "pc convert sketch missing_alias"
    Then the command should exit with a status code of "2"
