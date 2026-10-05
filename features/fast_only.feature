@pc @fast-only
Feature: '--fast-only' leaves out what declares a 'timeout:'

  An assembly that declares 'timeout:' is one its package says is slow: the
  daemon tells the client to wait that long while it works on it, and a command
  run with '--fast-only' passes over it -- which is what a sweep over a large
  tree in CI wants. It is read from the declaration alone, so nothing here
  builds anything and none of it needs a CAD sandbox.

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a directory named "package_a" exists
    And a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      assemblies:
        quick:
          type: assy
          desc: Quick Root Tower
      """
    And a file named "quick.assy" with content:
      """
      links: []
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      assemblies:
        slow:
          type: assy
          desc: Slow Skyscraper
          timeout: 1800
      """
    And a file named "package_a/slow.assy" with content:
      """
      links: []
      """

  @success
  Scenario: A recursive listing with '--fast-only' leaves out the slow assembly
    When I run "pc --no-ansi list assemblies -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Quick Root Tower"
    And STDERR should contain "Slow Skyscraper"
    When I run "pc --no-ansi list assemblies -r --fast-only //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Quick Root Tower"
    And STDERR should not contain "Slow Skyscraper"

  @success
  Scenario: 'list all' hands '-f' on to the listings that hold assemblies
    When I run "pc --no-ansi list all -f //..."
    Then the command should exit with a status code of "0"
    And STDERR should contain "Quick Root Tower"
    And STDERR should not contain "Slow Skyscraper"

  @success
  Scenario: A search with '--fast-only' leaves out the slow assembly
    When I run "pc --no-ansi search assemblies -r --fast-only -P // -k skyscraper"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Slow Skyscraper"
    When I run "pc --no-ansi search assemblies -r -P // -k skyscraper"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Slow Skyscraper"

  @success
  Scenario: A slow assembly named outright is passed over, and says so
    When I run "pc --no-ansi test -f nosuchcheck --fast-only -a //package_a:slow"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Skipping the assembly '//package_a:slow': it declares 'timeout: 1800'"
