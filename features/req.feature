@cli @pc-req
Feature: `pc req` command

  # What an object is required to be, changed one requirement at a time and read
  # back. Nothing here is built: the requirements are a declaration, and every
  # scenario works on a 'basic' part, which the daemon makes in-process -- so no
  # scenario provisions a CAD sandbox.
  #
  # Arguments are double-quoted and standard input comes from a file, never from
  # 'echo': on Windows a command runs in cmd.exe, where single quotes quote
  # nothing, '>' is a redirection, and 'echo' keeps the quotes it is given.

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" with content:
      """
      parts:
        # The part under test.
        bracket:
          type: basic
          cuboid: [20, 10, 5]
        old-bracket:
          type: basic
          cuboid: [20, 10, 6]
      """

  @success @pc-req-add
  Scenario: `pc req add` takes a requirement from the command line alone, and `pc req list` prints it as YAML
    When I run "pc --no-ansi req add physics bracket mass --value ">0,<=0.05""
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi req add port bracket top --direction 0 0 -1"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi req add has bracket private_dependencies --not"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should contain "mass: '>0,<=0.05'"
    And a file named "partcad.yaml" should contain "direction: [0, 0, -1]"
    And a file named "partcad.yaml" should contain "# The part under test."
    When I run "pc --no-ansi req list bracket"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "object: //:bracket"
    And STDOUT should contain "mass: '>0,<=0.05'"
    And STDOUT should contain "has_private_dependencies: false"

  @success @pc-req-add
  Scenario: `pc req add --stdin` reads YAML with YAML's quoting, and a comparison left unquoted says to quote it
    Given a file named "center.txt" with content
      """
      [null, null, '<5']
      """
    When I run "pc --no-ansi req add physics bracket centerOfMass --stdin < center.txt"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should contain "centerOfMass: [null, null, <5]"
    Given a file named "mass.txt" with content
      """
      >0
      """
    When I run "pc --no-ansi req add physics bracket mass --stdin < mass.txt 2>&1"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "quote it"
    And a file named "partcad.yaml" should not contain "mass:"

  @success @pc-req-add
  Scenario: `pc req add` refuses a requirement that is there already, unless told to replace it
    When I run "pc --no-ansi req add match bracket :old-bracket --weight 5"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi req add match bracket :old-bracket --mass 4 2>&1"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "--replace"
    When I run "pc --no-ansi req add match bracket :old-bracket --mass 4 --replace"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should contain "mass: 4"

  @success @pc-req-remove
  Scenario: `pc req rm` takes a requirement out, and the section with it once nothing is left
    When I run "pc --no-ansi req add feature bracket mount "Takes an M3 screw from either side""
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should contain "mount: Takes an M3 screw from either side"
    When I run "pc --no-ansi req rm feature bracket mount"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should not contain "requirements:"
