@cli @add-software
Feature: `pc add software` command

  Background: Initialize PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist
    When I run "partcad --no-ansi init -p"
    Then the command should exit with a status code of "0"

  @success
  Scenario: Add software the package carries
    Given a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    # One word, and no quotes: the step runs the command through a shell, and
    # `cmd.exe` does not treat single quotes as quoting -- so a quoted value with
    # spaces in it arrives at the CLI split into three arguments, and the command
    # fails on Windows and nowhere else. What is under test is that `--desc`
    # reaches the declaration, which one word shows just as well.
    When I run "partcad add software firmware.bin --desc controller-image"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Adding the software firmware.bin"
    And STDOUT should contain "Software 'firmware' added to the project."
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      software:
        firmware:
          desc: controller-image
          path: firmware.bin
      """

  @success
  Scenario: The added software is listed
    Given a file named "firmware.bin" with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "partcad add software firmware.bin"
    Then the command should exit with a status code of "0"
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "firmware"
    And STDOUT should contain "Total: 1"

  @failure
  Scenario: Software that is not there is refused
    When I run "partcad add software nowhere.bin"
    Then the command should exit with a non-zero status code
    # Nothing was written: a usage error leaves the package as it was.
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "<none>"

  @success
  Scenario: Add software from a URL, pinned by the hash of what came back
    # The point of the URL form: a piece of software cannot be bought by vendor
    # and SKU, so a file the package neither carries nor pins is one nothing
    # identifies. `pc add` fetches once and writes the hash, so the declaration
    # is reproducible from the moment it exists.
    Given "firmware.bin" is served over HTTP with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "partcad add software $PC_TEST_HTTP_URL/firmware.bin"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Software 'firmware' added to the project."
    And a file named "partcad.yaml" should contain "fileFrom: url"
    And a file named "partcad.yaml" should contain "fileHash: sha256:dd20df4dd573bce521655bd99622da79ad904afad39d77f0dea18e590ef56bd6"
    # The fetched copy is not kept: the package declares where to get the file,
    # it does not carry it. `pc install` fetches it when it is first needed.
    And a file named "firmware.bin" should not exist

  @failure
  Scenario: A URL that answers with an error adds nothing
    # Without the bytes there is no hash, and a declaration written without one
    # is the unpinned declaration the fetch exists to avoid.
    Given "firmware.bin" is served over HTTP with content:
      """
      PARTCAD-BEHAVE-FIRMWARE
      """
    When I run "partcad add software $PC_TEST_HTTP_URL/nowhere.bin"
    Then the command should exit with a non-zero status code
    When I run "pc list software"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "<none>"
