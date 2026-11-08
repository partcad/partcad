@cli @pc-qual
Feature: `pc qual` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-qual-sim
  Scenario: A simulation declared under 'qual: sim:' is run by the plugin its 'path:' names
    # Simulations are the 'sim' subtype of qualification, declared under
    # 'qual: sim:' with the plugin as 'path:', and '--simulation' alone runs
    # them and says what each found. This one names a plugin the package does
    # not declare, so it fails before anything is built -- no geometry, no
    # scene, no sandbox -- and fails on any machine.
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: step
          path: block.step
          qual:
            sim:
              stands:
                path: :nosuch
                validation: after["bodies"]["block"]["pos"][2] > 5.0
      """
    And a file named "block.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    When I run "pc qual test --simulation block"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "//:block: the simulation 'stands' failed"
    And STDOUT should contain "declares no simulation 'nosuch'"
    And STDERR should contain "1 of 1 simulation(s) did not pass"

  @success @pc-qual-other
  Scenario: A test a plugin supplies is run only where it is declared, and fails naming a plugin nobody declares
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: step
          path: block.step
          manufacturable: false
          qual:
            other:
              budgets:
                path: :nosuch
                lockfile: rover.lockwire.yaml
      """
    And a file named "block.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    When I run "pc qual test --other block"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "budgets: the check 'budgets' could not be run"
    And STDOUT should contain "declares no qualification plugin 'nosuch'"

  @success @pc-qual-add
  Scenario: `pc qual add` writes a built-in test's parameters into the object's declaration
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: step
          path: block.step
      """
    And a file named "block.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    When I run "pc qual add --topology --set minArea=1.5 block tolerance-surfaces"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should contain "tolerance-surfaces:"
    And a file named "partcad.yaml" should contain "minArea: 1.5"

  @success @pc-qual-add
  Scenario: `pc qual add` refuses a test that is neither built in nor a plugin's
    Given a file named "partcad.yaml" with content:
      """
      parts:
        block:
          type: step
          path: block.step
      """
    And a file named "block.step" with content:
      """
      ISO-10303-21;
      HEADER;
      ENDSEC;
      DATA;
      ENDSEC;
      END-ISO-10303-21;
      """
    When I run "pc qual add --basic --set x=1 block nothing"
    Then the command should exit with a status code of "2"
    And a file named "partcad.yaml" should not contain "qual:"
