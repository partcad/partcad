@cli @pc-lint
Feature: `pc lint` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success
  Scenario: Valid YAML passes lint check
    Given a file named "partcad.yaml" with content:
      """
      desc: A test project
      private: true
      manufacturable: false
      url: https://www.example.com
      poc: Jane Doe
      partcad: ">=0.7.134"
      pythonVersion: "3.10.1"
      pythonRequirements: ["numpy", "pydantic"]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Unexpected top-level key should raise an error
    Given a file named "partcad.yaml" with content:
      """
      desc: Contains unexpected key
      foo: bar
      private: false
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "$: Additional properties are not allowed ('foo' was unexpected)"

  @failure
  Scenario: Unexpected subkey give warning
    Given a file named "partcad.yaml" with content:
      """
      desc: Testing nested subkeys
      dependencies:
        core:
          type: git
          foo: bar
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "$.dependencies.core: Additional properties are not allowed ('foo' was unexpected)"

  @failure
  Scenario: Invalid enum value in part type
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid part type
      private: false
      parts:
        part1:
          type: unknown_type
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.part1.type: 'unknown_type' is not one of"

  @failure
  Scenario: Invalid enum in shape parameters
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid enum in parameters
      parts:
        component1:
          type: cadquery
          parameters:
            length:
              type: nonsense
      """

    And a file named "component1.py" with content:
      """
      # This is a py file for component1.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "'nonsense' is not one of ['string', 'int', 'bool', 'float']"

  @success
  Scenario: Fully valid configuration with deeply nested parameters
    Given a file named "partcad.yaml" with content:
      """
      desc: Everything correctly configured
      private: false
      pythonVersion: "3.11.2"
      pythonRequirements: ["pandas"]
      parts:
        body:
          type: build123d
          pythonRequirements: ["build123d>=0.8.0"]
          parameters:
            size:
              type: int
              default: 10
            kind:
              type: string
              enum: ["X", "Y", "Z"]
              default: "Y"
              color: "#FF0000"
              material: "steel"
          patch:
            weld: "enabled"
      dependencies:
        corelib:
          type: git
          url: "https://github.com/example/corelib.git"
          revision: "main"
      cover:
        package: "mainpkg"
        assembly: "assy"
      """
    And a file named "body.py" with content:
      """
      # This is a py file for body.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Invalid provider type
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid enum in providers
      providers:
        localstore:
          type: s3
          desc: Cloud bucket
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.providers.localstore.type: 's3' is not one of ['store', 'manufacturer', 'enrich']"

  @failure
  Scenario: Invalid value for pythonRequirements
    Given a file named "partcad.yaml" with content:
      """
      desc: This should fail type checks
      pythonRequirements: "should-be-a-list"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.pythonRequirements: 'should-be-a-list' is not of type 'array'"

  @success
  Scenario: Valid sketch with rectangle, square, and circle
    Given a file named "partcad.yaml" with content:
      """
      desc: Valid sketch types
      sketches:
        baseSketch:
          type: dxf
          path: "base.dxf"
          rectangle:
            side-x: 10
            side-y: 5
            x: 0
            y: 0
          circle:
            radius: 5
            x: 1
            y: 1
          square:
            side: 4
            x: 2
            y: 2
      """
    And a file named "base.dxf" with content:
      """
      This is a dxf file for base.dxf
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Sketch with missing required properties in rectangle
    Given a file named "partcad.yaml" with content:
      """
      sketches:
        shape:
          type: svg
          rectangle:
            side-x: 10
      """
    And a file named "shape.svg" with content:
      """
      This is a svg file for shape.svg
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.sketches.shape.rectangle: 'side-y' is a required property"

  @failure
  Scenario: Part with invalid axis format
    Given a file named "partcad.yaml" with content:
      """
      parts:
        extruder:
          type: sweep
          axis:
            - [1, 2]
            - [1, 2, 3]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.extruder.axis[0]: [1, 2] is too short"

  @success
  Scenario: Interface with valid parameters and ports
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
        board_iface:
          abstract: true
          path: "./interfaces/board.iface"
          ports:
            portA:
              location:
                - [0, 0, 0]
                - [1, 0, 0]
                - 0
              sketch: "conn"
          parameters:
            move-x:
              min: 0
              max: 10
              default: 5
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Part with provider, model, and AI-related fields
    Given a file named "partcad.yaml" with content:
      """
      parts:
        aiBlock:
          type: ai-cadquery
          provider: openai
          model: gpt-4
          tokens: 256
          temperature: 0.7
          top_p: 0.95
          top_k: 40
          desc: Generate a 3D model of a cube
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Part with invalid top_p value
    Given a file named "partcad.yaml" with content:
      """
      parts:
        gen:
          type: ai-build123d
          provider: openai
          model: gpt-4
          tokens: 256
          temperature: 0.7
          top_p: 1.95
          top_k: 40
          desc: Generate a 3D model of a cube
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.gen.top_p: 1.95 is greater than the maximum of 1.0"

  @failure
  Scenario: Parameters with invalid nested enum in providers
    Given a file named "partcad.yaml" with content:
      """
      providers:
        buildTool:
          type: manufacturer
          parameters:
            configMode:
              type: string
              enum: [1, 2, 3]
      """
    And a file named "buildTool.py" with content:
      """
      # This is a py file for buildTool.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.providers.buildTool.parameters.configMode.enum[0]: 1 is not of type 'string'"

  @failure
  Scenario: Part with invalid offset array
    Given a file named "partcad.yaml" with content:
      """
      parts:
        shape:
          type: extrude
          depth: 2.0
          offset:
            - [1, 2, "bad"]
            - [0, 0, 1]
            - 0
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "'bad' is not of type 'number'"

  @success
  Scenario: Valid OCCTLocation in part offset
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: cadquery
          offset:
            - [1.0, 2.0, 3.0]
            - [0.0, 0.0, 1.0]
            - 0.0
      """
    And a file named "block.py" with content:
      """
      # This is a py file for block.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Invalid OCCTLocation with wrong item count
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: cadquery
          offset:
            - [1.0, 2.0]
            - [0.0, 0.0, 1.0]
            - 0.0
      """
    And a file named "block.py" with content:
      """
      # This is a py file for block.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.block.offset[0]: [1.0, 2.0] is too short"

  @success
  Scenario: Valid interface-parameter with directional parameters
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
        mech:
          path: "./mech.iface"
          parameters:
            custom_axis:
              min: -10
              max: 10
              default: 0
              dir: [1, 0, 0]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Invalid interface-parameter missing dir
    Given a file named "partcad.yaml" with content:
      """
      interfaces:
        mech:
          path: "./mech.iface"
          parameters:
            custom_axis:
              min: -10
              max: 10
              default: 0
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.interfaces.mech.parameters.custom_axis: 'dir' is a required property"

  @success
  Scenario: Valid assembly with parameters
    Given a file named "partcad.yaml" with content:
      """
      assemblies:
        main:
          type: assy
          desc: Main assembly
          parameters:
            width:
              type: float
              default: 10.5
              color: "#00FF00"
          offset:
            - [0, 0, 0]
            - [0, 0, 1]
            - 0
      """
    And a file named "main.assy" with content:
      """
      This is a assembly file for main.assy
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Valid render configuration
    Given a file named "partcad.yaml" with content:
      """
      desc: Valid render config
      render:
        png:
          prefix: "render_"
          width: 800
          height: 600
          exclude: ["sketches", "interfaces"]
        markdown: "README.md"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Invalid render with unexpected property
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid render config
      render:
        png:
          prefix: "render_"
          invalid_key: true
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "$.render.png: Additional properties are not allowed ('invalid_key' was unexpected)"

  @success
  Scenario: Valid suppliers configuration
    Given a file named "partcad.yaml" with content:
      """
      desc: Valid suppliers
      suppliers:
        - "vendor1"
        - "vendor2"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Invalid suppliers with non-string items
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid suppliers
      suppliers:
        - 123
        - "vendor2"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.suppliers[0]: 123 is not of type 'string'"

  @success
  Scenario: Valid part with implements and ports
    Given a file named "partcad.yaml" with content:
      """
      parts:
        component:
          type: cadquery
          implements:
            iface1:
              location:
                - [0, 0, 0]
                - [1, 0, 0]
                - 0
          ports:
            port1:
              location:
                - [1, 1, 1]
                - [0, 0, 1]
                - 0
              sketch: "port_sketch"
      """
    And a file named "component.py" with content:
      """
      # This is a py file for component.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Invalid implements with incorrect structure
    Given a file named "partcad.yaml" with content:
      """
      parts:
        component:
          type: cadquery
          implements:
            iface1:
              invalid_field: true
      """
    And a file named "component.py" with content:
      """
      # This is a py file for component.py
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.component.implements.iface1: {'invalid_field': True} is not valid under any of the given schemas"
