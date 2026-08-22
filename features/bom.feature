@cli @pc-bom
Feature: `pc bom` command

  Background: A package with an assembly of assemblies
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          desc: A cube

      assemblies:
        unit:
          type: assy
          desc: A pair of cubes, also sold assembled
          vendor: partcad
          sku: UNIT-1
        top:
          type: assy
          desc: The top level assembly
      """
    And a file named "cube.py" with content:
      """
      import cadquery as cq

      shape = cq.Workplane("XY").box(1, 1, 1)
      show_object(shape)
      """
    And a file named "unit.assy" with content:
      """
      links:
        - part: cube
          name: cube1
          location: [[0,0,0], [0,0,1], 0]
        - part: cube
          name: cube2
          location: [[0,0,1], [0,0,1], 0]
      """
    And a file named "top.assy" with content:
      """
      links:
        - assembly: unit
          name: unit1
          location: [[0,0,0], [0,0,1], 0]
        - assembly: unit
          name: unit2
          location: [[0,0,10], [0,0,1], 0]
        - part: cube
          location: [[0,0,20], [0,0,1], 0]
      """

  @success @pc-bom
  Scenario: The bill of materials counts the whole tree
    When I run "pc bom :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Bill of materials of //:top:"
    # Two units of two cubes each, plus the one the top level assembly holds.
    And STDOUT should contain "//:cube"
    And STDOUT should contain "Total: 5"
    And STDOUT should contain "DONE: BoM: //: top"

  @success @pc-bom
  Scenario: The bill of materials in JSON
    When I run "pc -q bom --json :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain '"assembly": "//:top"'
    And STDOUT should contain '"name": "//:cube"'
    And STDOUT should contain '"kind": "part"'
    And STDOUT should contain '"count": 5'
    And STDOUT should contain '"total": 5'

  @success @pc-bom
  Scenario: A sub-assembly nobody supplies is expanded even when it names an SKU
    # The unit declares a vendor and an SKU, but the package declares no
    # supplier, so there is nowhere to buy it: it is still an assembly to build.
    When I run "pc bom --stop-at-purchasable :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Total: 5"
    # A purchased line item is the only thing that prints an SKU to order by.
    And STDOUT should not contain "UNIT-1"

  @success @pc-bom
  Scenario: A part is not an assembly
    When I run "pc bom :cube"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Assembly //:cube is not found"
