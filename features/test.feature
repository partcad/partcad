@cli @pc-test
Feature: `pc test` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @wip
  Scenario: `pc test -s //pub/std/metric/m:m3`
    Given I have a valid PartCAD configuration
    When I execute "pc test -s //pub/std/metric/m:m3"
    Then the command should exit with code 0
    And the output should contain "Test completed successfully"
    And no errors should be reported

  # @success
  # Scenario: `Recursively test all imported packages and pass`
  #   Given a file named "partcad.yaml" with content:
  #     """
  #     dependencies:
  #       gobilda:
  #         type: git
  #         url: https://github.com/partcad/partcad-robotics-part-vendor-gobilda
  #     """
  #   When I run "pc test -r"
  #   Then the command should exit with a status code of "0"
  #   Then STDOUT should contain "Git operations: 1"
  #   Then STDOUT should contain "DONE: Test: //"

  @success
  Scenario: `Recursively test all imported packages and fail`
    Given a file named "partcad.yaml" with content:
      """
      dependencies:
        dfrobot:
          type: git
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    When I run "pc test -r"
    Then the command should exit with a status code of "1"
    Then STDOUT should contain "Git operations: 1"
    Then STDOUT should contain "manufacturability: No suppliers found"
    Then STDOUT should contain "DONE: Test: //"

  @success @pc-test @pc-test-reproducibility
  Scenario: A part fetched from a URL and pinned by nothing is not manufacturable
    # 'manufacturability' only, and nothing is fetched: the declaration alone settles it, so
    # no geometry is built and no request is made.
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      parts:
        bolt:
          type: step
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
      """
    When I run "pc test -f manufacturability bolt"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "It is not reproducible"
    And STDOUT should contain "declares no 'fileHash'"

  @success @pc-test
  Scenario: `pc test -P` looks the object up in the given package
    # 'manufacturability' only, as above: the declaration alone settles it, so the scenario
    # costs nothing to build. What it holds is where 'bolt' was looked for.
    Given a directory named "sub" exists
    And a file named "sub/partcad.yaml" with content:
      """
      manufacturable: true

      parts:
        bolt:
          type: step
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
      """
    And a file named "partcad.yaml" with content:
      """
      import:
        sub:
          path: sub
      """
    When I run "pc test -P //sub -f manufacturability bolt"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "declares no 'fileHash'"

  @success @pc-test @pc-test-reproducibility
  Scenario: The same part is reproducible once the download is pinned
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      parts:
        bolt:
          type: step
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
          fileHash: sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae
      """
    When I run "pc test -f manufacturability bolt"
    # It still has no way of being made or bought, so the test still fails --
    # but reproducibility is no longer what is wrong with it.
    Then STDOUT should not contain "not reproducible"

  @success @pc-test @pc-test-reproducibility
  Scenario: A part that is bought is reproducible without a hash
    # A vendor and an SKU say what to order, and ordering the same SKU again is
    # what "the same again" means for a bought thing. The file it draws is a
    # picture of what arrives rather than the identity of it.
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      parts:
        bolt:
          type: step
          vendor: partcad
          sku: BOLT-1
          fileFrom: url
          fileUrl: https://example.com/vendor/bolt.step
      """
    When I run "pc test -f manufacturability bolt"
    Then STDOUT should not contain "not reproducible"

  @success @pc-test @pc-test-software
  Scenario: A board whose image does not match its fileHash is not manufacturable
    # 'manufacturability' only: the siblings ('manufacturability-additive',
    # 'manufacturability-subtractive', ...) apply to a part that is made rather
    # than bought, and this one is bought, so nothing here needs the geometry
    # built.
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      software:
        firmware:
          desc: What the board runs
          path: firmware.bin
          fileHash: sha256:0000000000000000000000000000000000000000000000000000000000000000

      parts:
        board:
          type: cadquery
          desc: A board bought off the shelf, flashed with an image of ours
          vendor: partcad
          sku: BOARD-1
          software:
            - firmware
      """
    And a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    And a file named "board.py" with content:
      """
      import cadquery as cq

      shape = cq.Workplane("XY").box(40, 25, 1.6)
      show_object(shape)
      """
    When I run "pc test -f manufacturability board"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "//:firmware"
    And STDOUT should contain "does not match its 'fileHash'"

  @success @pc-test @pc-test-software
  Scenario: A board whose image the package carries is manufacturable
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      software:
        firmware:
          desc: What the board runs
          path: firmware.bin

      parts:
        board:
          type: cadquery
          desc: A board bought off the shelf, flashed with an image of ours
          vendor: partcad
          sku: BOARD-1
          software:
            - firmware
      """
    And a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    And a file named "board.py" with content:
      """
      import cadquery as cq

      shape = cq.Workplane("XY").box(40, 25, 1.6)
      show_object(shape)
      """
    When I run "pc test -f manufacturability board"
    # The package declares no supplier, so the part still has nowhere to be
    # bought from -- but the software is no longer what is wrong with it.
    Then STDOUT should not contain "cannot be relied on"

  @success @pc-test @pc-test-tolerance
  Scenario: A STEP part says how precisely it is made, in the declaration or in the file
    # A 'step' part rejects the 'tolerance' parameter -- a STEP file may hold
    # many solids -- and answers with a field of its own, or with what its file
    # already states. Three parts rather than three scenarios: each scenario
    # takes a temporary $HOME and builds a sandbox of its own, and one "pc test"
    # over one package proves the same three things for a third of the cost.
    #
    #   bracket   declares a tolerance the file does not state
    #   plain     states none anywhere, which is a demand for perfect precision
    #   tolerated is tolerated feature by feature, 0.05 on one face and 0.2 on
    #             another: no single number is true of it, and none is invented
    #
    # All three lack a supplier, so all three fail -- on that, which is what
    # proves the tolerance check let two of them through.
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      parts:
        bracket:
          type: step
          manufacturing:
            method: subtractive
          tolerance: 0.1
        plain:
          type: step
          manufacturing:
            method: subtractive
        tolerated:
          type: step
          manufacturing:
            method: subtractive
      """
    And a file named "bracket.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    And a file named "plain.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    And a file named "tolerated.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      #10=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));
      #200=FLATNESS_TOLERANCE('','',#201,#900);
      #201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);
      #210=FLATNESS_TOLERANCE('','',#211,#900);
      #211=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.2),#10);
      ENDSEC;
      END-ISO-10303-21;
      """
    When I run "pc test -f manufacturability"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "//:plain: manufacturability: No manufacturing tolerance is specified"
    And STDOUT should contain "//:bracket: manufacturability: No suppliers found"
    And STDOUT should contain "//:tolerated: manufacturability: No suppliers found"

  @wip
  Scenario: Test with invalid configuration
    Given I have an invalid PartCAD configuration
    When I execute "pc test -s //pub/std/metric/m:m3"
    Then the command should exit with non-zero code
    And the output should contain "Configuration error"

  @wip
  Scenario: Test with non-existent part
    Given I have a valid PartCAD configuration
    When I execute "pc test -s //pub/non/existent/part"
    Then the command should exit with non-zero code
    And the output should contain "Part not found"
