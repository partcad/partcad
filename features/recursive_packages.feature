@pc @recursive-packages
Feature: A package name ending in '...' means that package and everything below it

  The written form of what '-r' does, with two things a flag cannot do: it says
  *where* the walk starts, and it can be written on an object name, so that one
  name means every object that answers to it in the subtree. A package of the
  subtree that declares no such object is passed over rather than reported --
  only a walk that found the object nowhere is a failure.

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a directory named "package_a" exists
    And a directory named "package_b" exists
    And a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      sketches:
        circle_root:
          desc: Circle Root
          type: basic
          circle: 1
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          circle: 5
        shared:
          desc: Shared A
          type: basic
          circle: 6
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          circle: 10
        shared:
          desc: Shared B
          type: basic
          circle: 11
      """

  @success
  Scenario: '...' on a package name walks the subtree, and without it nothing is walked
    When I run "pc --no-ansi list sketches //..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle Root"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"
    # The same package without the suffix: only what it declares itself.
    When I run "pc --no-ansi list sketches //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle Root"
    And STDERR should not contain "Circle A"
    And STDERR should not contain "Circle B"

  @success
  Scenario: The last path separator is optional, and '...' alone is "from here down"
    When I run "pc --no-ansi list sketches //package_a..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    When I run "pc --no-ansi list sketches //package_a/..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    When I run "pc --no-ansi list sketches ..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle Root"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"

  @success
  Scenario: '-r' still means the same thing
    When I run "pc --no-ansi list sketches -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"

  @success
  Scenario: A named object is looked for in every package of the subtree
    # '-f' selects no check at all, so this resolves the objects and runs
    # nothing: what is under test is which packages the name reached.
    When I run "pc --no-ansi test -s -f nosuchcheck ...:shared"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "is not found"

  @success
  Scenario: A package of the subtree that declares no such object is passed over
    When I run "pc --no-ansi test -s -f nosuchcheck ...:circle_a"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "is not found"

  @failure
  Scenario: Finding the object nowhere in the subtree is the one failure
    When I run "pc --no-ansi test -s -f nosuchcheck ...:nosuchsketch"
    Then the command should exit with a non-zero status code
    And STDERR should contain "nosuchsketch is not found in // or in any package below it"

  @success
  Scenario: An object name carrying the suffix says where the walk starts
    When I run "pc --no-ansi info -s //package_a...:shared"
    Then the command should exit with a status code of "0"
    And STDERR should contain "OBJECT: //package_a:shared"
    And STDERR should not contain "OBJECT: //package_b:shared"

  @success
  Scenario: A package suffix with no object reports every package of the subtree
    When I run "pc --no-ansi info -P //..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "PACKAGE: //"
    And STDERR should contain "PACKAGE: //package_a"
    And STDERR should contain "PACKAGE: //package_b"
