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
  Scenario: The bill of materials lists what has to be procured
    When I run "pc bom :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Bill of materials of //:top:"
    # The unit declares a vendor and an SKU, so it is ordered whole: two units,
    # plus the one cube the top level assembly holds. The cubes inside the units
    # are not listed.
    And STDOUT should contain "//:unit"
    And STDOUT should contain "UNIT-1"
    And STDOUT should contain "//:cube"
    And STDOUT should contain "Total: 3"
    And STDOUT should contain "DONE: BoM: //: top"

  @success @pc-bom
  Scenario: The bill of materials in JSON
    When I run "pc -q bom --json :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain '"assembly": "//:top"'
    And STDOUT should contain '"name": "//:unit"'
    And STDOUT should contain '"kind": "assembly"'
    And STDOUT should contain '"name": "//:cube"'
    And STDOUT should contain '"kind": "part"'
    And STDOUT should contain '"total": 3'

  @success @pc-bom
  Scenario: A sub-assembly that names an SKU is ordered whole whether or not anybody has one
    # The package declares no supplier, so nobody has a unit today. That is the
    # supply quote's question: the bill of materials says what to order, and the
    # unit says what to order it by. '--stop-at-purchasable' is still accepted.
    When I run "pc bom --stop-at-purchasable :top"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "UNIT-1"
    And STDOUT should contain "Total: 3"

  @success @pc-bom
  Scenario: A part's bill of materials is what it is procured as
    Given a file named "partcad.yaml" with content:
      """
      parts:
        sheet:
          type: cadquery
          path: cube.py
          desc: A sheet somebody sells
          vendor: acme
          sku: SHEET-1
        blank:
          type: cadquery
          path: cube.py
          desc: A blank cut out of the sheet
          manufacturing:
            method: subtractive
            source: sheet
        bracket:
          type: cadquery
          path: cube.py
          desc: A bracket bent from the blank
          manufacturing:
            method: sheet_metal
            source: blank
      """
    When I run "pc bom :bracket"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Bill of materials of //:bracket:"
    # Bent from the blank, which is cut from the sheet: one sheet, ordered by its
    # SKU, and nothing else - the blank and the bracket are made, not bought.
    And STDOUT should contain "//:sheet"
    And STDOUT should contain "SHEET-1"
    And STDOUT should contain "Total: 1"

  @success @pc-bom
  Scenario: The bill of materials lists the software the hardware ships with
    Given a file named "partcad.yaml" with content:
      """
      software:
        cube-firmware:
          desc: What a cube runs
          version: "2.0.0"
          path: cube-firmware.bin

      parts:
        cube:
          type: cadquery
          desc: A cube
          software:
            - cube-firmware

      assemblies:
        unit:
          type: assy
          desc: A pair of cubes
      """
    And a file named "cube-firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "pc bom :unit"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Software:"
    And STDOUT should contain "//:cube-firmware"
    # Two cubes to flash, counted apart from the two cubes themselves.
    And STDOUT should contain "Total: 2"
    And STDOUT should contain "Software total: 2"

  @success @pc-bom
  Scenario: A software line item names the package it came from, and its revision
    Given a file named "partcad.yaml" with content:
      """
      software:
        cube-firmware:
          desc: What a cube runs
          path: cube-firmware.bin

      parts:
        cube:
          type: cadquery
          desc: A cube
          software:
            - cube-firmware

      assemblies:
        unit:
          type: assy
          desc: A pair of cubes
      """
    And a file named "cube-firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "pc -q bom --json :unit"
    Then the command should exit with a status code of "0"
    And STDOUT should contain '"kind": "software"'
    And STDOUT should contain '"package": "//"'
    # Present whether or not this sandbox is a git repository: outside one there
    # is no commit to name, and the line says so rather than leaving it out.
    And STDOUT should contain '"revision"'
    And STDOUT should contain '"totalSoftware": 2'

  @success @pc-bom
  Scenario: A line item is ordered by the vendor and SKU it declares of its own
    # One piece of geometry sold by two vendors is two declarations over one
    # part, and the second is written as a reference to the first. What it is
    # bought as is the only thing such a reference restates, and it has to
    # survive being referenced again.
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cube:
          type: cadquery
          desc: A cube
          vendor: acme
          sku: CUBE-1
          count_per_sku: 10
        cube_from_other:
          type: alias
          source: cube
          vendor: other
          sku: OTHER-1
        cube_from_other_alias:
          type: alias
          source: cube_from_other

      assemblies:
        unit:
          type: assy
          desc: A cube bought from somewhere else
      """
    And a file named "unit.assy" with content:
      """
      links:
        - part: cube_from_other_alias
          location: [[0,0,0], [0,0,1], 0]
      """
    When I run "pc -q bom --json :unit"
    Then the command should exit with a status code of "0"
    And STDOUT should contain '"name": "//:cube_from_other_alias"'
    And STDOUT should contain '"vendor": "other"'
    And STDOUT should contain '"sku": "OTHER-1"'
    # The bag of ten belongs to acme's SKU and says nothing about this one.
    And STDOUT should contain '"count_per_sku": 1'

  @success @pc-bom
  Scenario: A part that says neither how it is bought nor how it is made is its own bill of materials
    When I run "pc bom :cube"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Bill of materials of //:cube:"
    And STDOUT should contain "Total: 1"
