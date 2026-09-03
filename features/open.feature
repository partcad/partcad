@cli @pc-open
Feature: `pc open` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @failure @pc-open
  Scenario: An unknown application is refused, and the known ones are named
    # Checked before anything is looked for, so this says the same thing on
    # every machine -- including one that has FreeCAD installed, where the
    # scenarios below must still not open a window.
    When I run "pc --no-ansi open --with solidworks cube.step"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "Unknown application"
    And OUTPUT should contain "freecad"
    And OUTPUT should contain "gazebo"
    And OUTPUT should contain "kicad"
    And OUTPUT should contain "blender"

  @failure @pc-open
  Scenario: A file that is not there is reported rather than opened
    Given a file named "cube.step" does not exist
    When I run "pc --no-ansi open cube.step"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: The reason survives --json, which the editor reads
    # A failure exits non-zero *and* prints the reason as JSON: the message is
    # the whole answer (what to install, how to allow a container), and the
    # VS Code extension's "Open in..." menu has nothing else to show the user.
    Given a file named "cube.step" does not exist
    When I run "pc --no-ansi open --json cube.step"
    Then the command should exit with a non-zero status code
    And STDOUT should contain '"ok": false'
    And STDOUT should contain "No such file"

  @failure @pc-open
  Scenario: A world file that is not there is reported rather than opened in Gazebo
    # The scene half of the "Open in..." menu: a '.world' file is what Gazebo
    # reads, and it is looked for on this machine exactly as a STEP file is.
    Given a file named "warehouse.world" does not exist
    When I run "pc --no-ansi open --with gazebo warehouse.world"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: A board that is not there is reported rather than opened in KiCad
    Given a file named "pcb.kicad_pro" does not exist
    When I run "pc --no-ansi open --with kicad pcb.kicad_pro"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: A part that is not there is reported rather than opened in Blender
    Given a file named "cube.stl" does not exist
    When I run "pc --no-ansi open --with blender cube.stl"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: The declared type is an option, and it is checked with the rest
    # The VS Code extension passes it for every object it opens; a `pc` that did
    # not accept it would fail as a usage error rather than for the reason here.
    Given a file named "cube.py" does not exist
    When I run "pc --no-ansi open --with blender --type cadquery cube.py"
    Then the command should exit with a non-zero status code
    And OUTPUT should contain "No such file"

  @failure @pc-open
  Scenario: A script whose type cannot be told from its name says what to pass
    # Blender reads meshes, so this file has to be converted -- and converting
    # it means running it, as one of the three kinds of script a '.py' can be.
    # Refused here, before a daemon is asked to guess, and no window is opened.
    # Read as JSON, which is one unwrapped line: the error panel `pc` draws
    # otherwise wraps to the terminal's width, and a message split across two
    # lines is not one a scenario can look for.
    When I run "pc --no-ansi open --json --with blender $PARTCAD_ROOT/examples/produce_part_cadquery_primitive/cylinder.py"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "--type"
    And STDOUT should contain "cadquery"

  @failure @pc-open
  Scenario: An ASSY file is refused by name rather than sent to be refused
    # There is no package around an ad-hoc file to resolve an ASSY against, so
    # `pc open` says so itself instead of asking the daemon to convert it.
    When I run "pc --no-ansi open --json --with blender $PARTCAD_ROOT/examples/produce_scene_assy/bench.assy"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "only means anything inside a package"
    And STDOUT should contain "pc export"
