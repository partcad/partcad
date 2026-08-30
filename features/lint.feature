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
    # A part 'type' is now anyOf {built-in enum, a '<package>:<partType>' reference},
    # so an unknown type fails the whole part schema rather than just the enum.
    And STDOUT should contain "$.parts.part1: {'type': 'unknown_type'} is not valid under any of the given schemas"

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
    # Same anyOf part schema: a bad parameter 'type' surfaces as the parameter
    # object failing its schemas, not as a bare enum error.
    And STDOUT should contain "{'type': 'nonsense'} is not valid under any of the given schemas"

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

  @success
  Scenario: Part, sketch and assembly with a source file pulled from a URL
    Given a file named "partcad.yaml" with content:
      """
      desc: Vendor files pulled from a URL
      parts:
        bolt:
          type: step
          path: bolt.step
          fileFrom: url
          fileUrl: https://example.com/vendor/catalog/bolt.step
      sketches:
        outline:
          type: dxf
          fileFrom: url
          fileUrl: https://example.com/vendor/catalog/outline.dxf
      assemblies:
        rig:
          type: assy
          fileFrom: url
          fileUrl: https://example.com/vendor/catalog/rig.assy
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: fileUrl without fileFrom
    # The file is there, so the package still loads and the schema check runs.
    # 'fileFrom' without 'fileUrl' is not linted the same way: the package
    # fails to load before any check runs. See test_lint_schema.py for the
    # schema itself, and test_file.py for what the loader reports.
    Given a file named "partcad.yaml" with content:
      """
      desc: Missing the source to download the file from
      parts:
        bolt:
          type: step
          fileUrl: https://example.com/vendor/catalog/bolt.step
      """
    And a file named "bolt.step" with content:
      """
      This is a step file for bolt.step
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.parts.bolt: 'fileFrom' is a dependency of 'fileUrl'"

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
      links:
        - part: bone
          package: //pub/examples
          location: [[0, 0, 0], [0, 0, 1], 0]
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
  Scenario: Render with a parameter of the implementation's own
    # A field of an output file type that is not one of the structural ones is
    # an export/render parameter, handed to whatever implements that file type.
    # Which parameters exist is up to the implementation - a package may add one
    # of its own along with an implementation of its own - so the schema cannot
    # close the set here.
    Given a file named "partcad.yaml" with content:
      """
      desc: Render config with an implementation parameter
      render:
        png:
          prefix: "render_"
          line_weight: 2.0
      export:
        step:
          comment: Not for manufacturing.
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
    And STDOUT should not contain "Additional properties are not allowed"

  @failure
  Scenario: Invalid render with a malformed structural property
    # The fields that say how the file is produced and where it goes are still
    # checked, even though the parameters around them are open-ended.
    Given a file named "partcad.yaml" with content:
      """
      desc: Invalid render config
      render:
        png:
          prefix: "render_"
          exclude: ["nonsense"]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "$.render.png.exclude[0]: 'nonsense' is not one of"

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

  @success
  Scenario: Valid ASSY file passes lint check
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with an assembly
      assemblies:
        logo:
          type: assy
      """
    And a file named "logo.assy" with content:
      """
      links:
        - part: bone
          package: //pub/examples
          location: [[0, 0, 0], [0, 0, 1], 0]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Jinja2 in an ASSY file is not mistaken for broken YAML
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with a parametrized assembly
      assemblies:
        desk:
          type: assy
      """
    And a file named "desk.assy" with content:
      """
      links:
        {% for x in [0, 1] %}
        - part: leg
          location: [[{{ x }}, 0, 0], [0, 0, 1], 0]
          params:
            length: {{ param_height }}
        {% endfor %}
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Misspelled ASSY property gives a warning at its line
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with an assembly
      assemblies:
        logo:
          type: assy
      """
    And a file named "logo.assy" with content:
      """
      links:
        - part: bone
          locaton: [[0, 0, 0], [0, 0, 1], 0]
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "logo.assy:3:5: unexpected property 'locaton'"

  @failure
  Scenario: Unclosed Jinja2 block in an ASSY file is an error
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with an assembly
      assemblies:
        desk:
          type: assy
      """
    And a file named "desk.assy" with content:
      """
      links:
        {% for x in [0, 1] %}
        - part: leg
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "desk.assy:2:1: Jinja2 template error"

  @failure
  Scenario: ASSY node that places nothing is an error
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with an assembly
      assemblies:
        logo:
          type: assy
      """
    And a file named "logo.assy" with content:
      """
      links:
        - name: nothing
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "logo.assy:2:5: expected at least one of 'links', 'part', 'assembly'"

  @success
  Scenario: `pc lint --file` checks a named file without a package
    Given a file named "logo.assy" with content:
      """
      links:
        - part: bone
          location: [[0, 0, 0], [0, 0, 1], 0]
      """
    When I run "pc lint --file logo.assy"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: `pc lint --file` reports findings at their source position
    Given a file named "logo.assy" with content:
      """
      links:
        - name: nothing
      """
    When I run "pc lint --file logo.assy"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "logo.assy:2:5: expected at least one of 'links', 'part', 'assembly'"

  @failure
  Scenario: An ASSY file a scene points at is checked without `how`
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with a scene
      scenes:
        bench:
          type: assy
      """
    And a file named "bench.assy" with content:
      """
      links:
        - part: bone
          package: //pub/examples
          name: bone
        - part: bone
          package: //pub/examples
          connect:
            name: bone
            how:
              stage: "1"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "bench.assy:9:7: 'how' is not allowed in a scene"

  @success
  Scenario: The same file, declared as an assembly, keeps its assembly instructions
    Given a file named "partcad.yaml" with content:
      """
      desc: A package with an assembly
      assemblies:
        bench:
          type: assy
      """
    And a file named "bench.assy" with content:
      """
      links:
        - part: bone
          package: //pub/examples
          name: bone
        - part: bone
          package: //pub/examples
          connect:
            name: bone
            how:
              stage: "1"
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: `pc lint --file --schema scene` says outright which schema to use
    Given a file named "bench.assy" with content:
      """
      links:
        - part: bone
          name: bone
        - part: bone
          connect:
            name: bone
            how:
              stage: "1"
      """
    When I run "pc lint --file bench.assy"
    Then the command should exit with a status code of "0"
    When I run "pc lint --file bench.assy --schema scene"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "bench.assy:7:7: 'how' is not allowed in a scene"

  @failure
  Scenario: `pc lint --file` rejects being mixed with the package options
    Given a file named "logo.assy" with content:
      """
      links:
        - part: bone
      """
    When I run "pc lint --file logo.assy --recursive"
    Then the command should exit with a status code of "2"

  @success
  Scenario: A part may pin the file it downloads
    Given a file named "partcad.yaml" with content:
      """
      desc: A part whose STEP file is pulled from the vendor and pinned
      parts:
        bolt:
          type: step
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
          fileHash: sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: A part that does not pin its download is not an error
    # Only software is required to be pinned. Everywhere else it is the
    # package's own choice, and demanding it would break every package that
    # already pulls a vendor's file from a URL.
    Given a file named "partcad.yaml" with content:
      """
      desc: A part whose STEP file is pulled from the vendor, unpinned
      parts:
        bolt:
          type: step
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @failure
  Scenario: Software pulled in from elsewhere has to be pinned by a fileHash
    Given a file named "partcad.yaml" with content:
      """
      desc: A package whose firmware is not in the package
      software:
        firmware:
          desc: A vendor image nothing identifies
          fileFrom: url
          fileUrl: https://example.com/vendor/firmware.bin
      """
    When I run "pc lint"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "software 'firmware' is fetched with 'fileFrom: url' and declares no 'fileHash'"

  @success
  Scenario: Software the package carries needs no hash
    Given a file named "partcad.yaml" with content:
      """
      desc: A package that carries its own firmware
      software:
        firmware:
          desc: The image this package carries
          path: firmware.bin
      """
    And a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Software pulled in with a fileHash passes
    Given a file named "partcad.yaml" with content:
      """
      desc: A package whose firmware is pinned
      software:
        firmware:
          desc: A vendor image, pinned
          fileFrom: url
          fileUrl: https://example.com/vendor/firmware.bin
          fileHash: sha256:0000000000000000000000000000000000000000000000000000000000000000
      """
    When I run "pc lint"
    Then the command should exit with a status code of "0"
