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
    Then STDOUT should contain "cam: No suppliers found"
    Then STDOUT should contain "DONE: Test: //"

  @success @pc-test @pc-test-software
  Scenario: A board whose image does not match its hash is not manufacturable
    # 'cam' only: the siblings ('cam-additive', 'cam-subtractive', ...) apply to
    # a part that is made rather than bought, and this one is bought, so nothing
    # here needs the geometry built.
    Given a file named "partcad.yaml" with content:
      """
      manufacturable: true

      software:
        firmware:
          desc: What the board runs
          path: firmware.bin
          hash: sha256:0000000000000000000000000000000000000000000000000000000000000000

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
    When I run "pc test -f cam board"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "//:firmware"
    And STDOUT should contain "does not match its 'hash'"

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
    When I run "pc test -f cam board"
    # The package declares no supplier, so the part still has nowhere to be
    # bought from -- but the software is no longer what is wrong with it.
    Then STDOUT should not contain "cannot be relied on"

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
