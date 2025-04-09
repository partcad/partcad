@cli @pc-lint
Feature: `pc lint` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success
  Scenario: Valid YAML passes lint check
    Given a file named "partcad.yaml" with content:
      """
      name: Example Project
      desc: A test project
      private: true
      manufacturable: false
      url: http://example.com
      poc: Jane Doe
      partcad: ">=0.7.134"
      pythonVersion: "3.10"
      pythonRequirements: ["numpy", "pydantic"]
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "configuration is valid"

  @failure
  Scenario: Missing required key should raise an error
    Given a file named "partcad.yaml" with content:
      """
      desc: Missing type key
      parts:
        part1:
          path: no_type.step
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: data.parts.part1 must contain ['type'] properties"

  @success
  Scenario: Unexpected top-level key should raise a warning
    Given a file named "partcad.yaml" with content:
      """
      name: Test
      desc: Contains unexpected key
      foo: bar
      private: false
      """
    When I run "pc --telemetry-type=none lint"
    Then STDOUT should contain "WARN: Validation Warning: data contains unexpected {'foo'} properties"
    And the command should exit with a status code of "0"

  @failure
  Scenario: Unexpected subkey inside dependencies
    Given a file named "partcad.yaml" with content:
      """
      name: Invalid dep subkey
      desc: Testing nested subkeys
      dependencies:
        core:
          type: git
          foo: bar
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "WARN: Validation Warning: data.dependencies.core contains unexpected {'foo'} properties"

  @failure
  Scenario: Invalid enum value in part type
    Given a file named "partcad.yaml" with content:
      """
      name: Test Enum
      desc: Invalid part type
      private: false
      parts:
        part1:
          type: unknown_type
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: data.parts.part1.type must be one of"

  @failure
  Scenario: Invalid enum inside parameters
    Given a file named "partcad.yaml" with content:
      """
      name: Invalid parameter type
      desc: Invalid enum in parameters
      parts:
        component1:
          type: cadquery
          parameters:
            length:
              type: nonsense
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: data.parts.component1.parameters.length.type must be one of"

  @success
  Scenario: Fully valid configuration with deeply nested parameters
    Given a file named "partcad.yaml" with content:
      """
      name: Complete Valid Config
      desc: Everything correctly configured
      private: false
      pythonVersion: "3.11"
      pythonRequirements: ["pandas"]
      parts:
        body:
          type: build123d
          pythonRequirements: ["build123d"]
          parameters:
            size:
              type: integer
              default: 10
            kind:
              type: string
              enum: ["X", "Y", "Z"]
              default: "Y"
          patch:
            weld: "enabled"
      dependencies:
        corelib:
          type: git
          url: "https://github.com/example/corelib"
          revision: "main"
      cover:
        package: "mainpkg"
        assembly: "assy"
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "configuration is valid"

  @failure
  Scenario: Invalid provider type
    Given a file named "partcad.yaml" with content:
      """
      name: Invalid provider
      desc: Invalid enum in providers
      providers:
        localstore:
          type: s3
          desc: Cloud bucket
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: data.providers.localstore.type must be one of"

  @failure
  Scenario: Invalid value for several fields
    Given a file named "partcad.yaml" with content:
      """
      name: Invalid type test
      desc: This should fail type checks
      pythonRequirements: "should-be-a-list"
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Validation Error: data.pythonRequirements must be array"

  @success
  Scenario: Valid sketch with rectangle, square, and circle
    Given a file named "partcad.yaml" with content:
      """
      name: Sketch Test
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
          circle: 5
          square:
            side: 4
            x: 2
            y: 2
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "configuration is valid"

  @failure
  Scenario: Sketch with missing required properties in rectangle
    Given a file named "partcad.yaml" with content:
      """
      name: Sketch Invalid
      sketches:
        shape:
          type: svg
          rectangle:
            side-x: 10
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error"

  @failure
  Scenario: Part with invalid axis format
    Given a file named "partcad.yaml" with content:
      """
      name: Axis Test
      parts:
        extruder:
          type: sweep
          axis:
            - [1, 2]    # invalid, should be 3 numbers
            - [1, 2, 3]
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error"

  @success
  Scenario: Interface with valid parameters and ports
    Given a file named "partcad.yaml" with content:
      """
      name: Interface Test
      interfaces:
        board_iface:
          abstract: true
          path: "./interfaces/board.iface"
          ports:
            portA:
              location: "left"
              sketch: "conn"
          parameters:
            moveZ:
              min: 0
              max: 10
              default: 5
              type: move
              dir: [0, 0, 1]
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Part with provider, model, and AI-related fields
    Given a file named "partcad.yaml" with content:
      """
      name: AI Part Test
      parts:
        aiBlock:
          type: ai-cadquery
          provider: openai
          model: gpt-4
          tokens: 256
          temperature: 0.7
          top_p: 0.95
          top_k: 40
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Part with invalid top_p value
    Given a file named "partcad.yaml" with content:
      """
      name: Invalid top_p
      parts:
        gen:
          type: ai-build123d
          provider: ollama
          top_p: 1.5
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: data.parts.gen.top_p must be smaller than or equal to 1.0"

  @failure
  Scenario: Parameters with invalid nested enum in providers
    Given a file named "partcad.yaml" with content:
      """
      name: Param Enum Fail
      providers:
        buildTool:
          type: manufacturer
          parameters:
            configMode:
              type: string
              enum: [1, 2, 3]
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error: "

  @failure
  Scenario: Part with offset array not matching expected types
    Given a file named "partcad.yaml" with content:
      """
      name: Bad Offset
      parts:
        shape:
          type: extrude
          offset:
            - [1, 2, "bad"]  # Invalid non-numeric entry
      """
    When I run "pc --telemetry-type=none lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "ERROR: Validation Error"
