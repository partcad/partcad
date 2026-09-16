@cli @pc-cam
Feature: `pc cam` command

  `pc cam` writes the program a machine cuts an object with. An object opts in
  by declaring a `cam:` section, and that section is the whole of the opt-in:
  with nothing named, every sketch and part of the package that declares one is
  routed and everything else is passed over in silence.

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # ------------------------------------------------------------------------ #
  # The one scenario that builds geometry                                     #
  # ------------------------------------------------------------------------ #

  # Every scenario here gets a `$HOME` of its own, so every scenario that builds
  # a shape builds a CAD sandbox from nothing -- gigabytes, and minutes of pip.
  # So there is exactly one of those in this feature, and it asks everything
  # that needs a real route in one go: several `When I run` steps against one
  # prepared package share the sandbox the first one paid for.
  @success @pc-cam @pc-cam-route
  Scenario: A part that declares `cam:` is routed, and one that does not is passed over
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
          cam:
            operation: profile
            tool: 6 mm
            depth_per_pass: 6 mm
            feed: 1200 mm/min
            speed: 18000 rpm
        spacer:
          type: build123d
          path: panel.py
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(80, 50, 12)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi cam"
    Then the command should exit with a status code of "0"
    # The route is named after the object alone -- `panel.nc`, because an object
    # has one route at a time and the extension says what the file is.
    And a file named "panel.nc" should be created
    # G21 is millimetres, M30 ends the program: the file is a program and not a
    # half-written one. `18.000` would be the panel's thickness if the depth had
    # been read from the wrong end -- it is 12 mm, in two 6 mm passes.
    And a file named "panel.nc" should contain "G21"
    And a file named "panel.nc" should contain "M30"
    And a file named "panel.nc" should contain "depth 12.000 in 2 passes"
    # The spindle speed the part named, as an M3/M5 pair.
    And a file named "panel.nc" should contain "M3 S18000"
    # `spacer` declares no `cam:` section, so nothing was produced for it and
    # nothing was said about it.
    And a file named "spacer.nc" should not exist
    And STDERR should contain "panel.nc"
    # The same package, one object at a time.
    When I run "pc --no-ansi cam :panel"
    Then the command should exit with a status code of "0"
    # And as data, which is what something downstream of this would read.
    When I run "pc --no-ansi cam --json :panel"
    Then the command should exit with a status code of "0"
    # The single-quoted step variant, because the text being looked for has
    # double quotes of its own and behave's parser does not read backslash
    # escapes inside a step argument.
    And STDOUT should contain '//builtin/cam:gcode'
    And STDOUT should contain '"operation": "profile"'
    # Naming an object that declares nothing is an error, because naming one is
    # asking about it -- unlike the silence it earns in a whole-package run.
    When I run "pc --no-ansi cam --json :spacer"
    Then the command should exit with a status code of "1"
    And STDERR should contain "declares no 'cam:' section"
    # And the array is printed even so. A failure must not swallow the record of
    # what *was* produced -- here there is nothing, but the same path carries
    # the nineteen routes that worked when the twentieth object is misconfigured.
    And STDOUT should contain "[]"
    # A name nothing resolves to is a failure of the object the user typed, not
    # an empty success: the array prints, and the command still exits non-zero.
    When I run "pc --no-ansi cam :nosuchpart"
    Then the command should exit with a status code of "1"
    And STDERR should contain "No route was produced for"

  # ------------------------------------------------------------------------ #
  # Everything below is settled by the declaration alone                      #
  # ------------------------------------------------------------------------ #

  # No geometry is built for any of these: `Shape.route_async()` reads the
  # object's section before it asks for the shape, so a section that cannot be
  # read costs nothing at all. That is what makes them cheap enough to have.

  @success @pc-cam
  Scenario: A package where nothing declares `cam:` says so rather than saying nothing
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi cam"
    Then the command should exit with a status code of "0"
    # Saying nothing would look exactly like a route that went somewhere the
    # user did not notice.
    And STDERR should contain "declares a 'cam:' section, so no route was produced"

  @success @pc-cam
  Scenario: A value that cannot be read as a length is refused, by object and by key
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
          cam:
            tool: six millimetres
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi cam"
    Then the command should exit with a status code of "1"
    # Named, because a run over a package prints one line per object and a
    # sentence with no address on it is one nobody can act on.
    And STDERR should contain ":panel: 'cam: tool:' is not a length"

  @success @pc-cam
  Scenario: A key that is not a job parameter is refused rather than ignored
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
          cam:
            tool: 6 mm
            toool: 3 mm
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi cam"
    Then the command should exit with a status code of "1"
    # A closed set of keys is what turns a typo into a sentence instead of a
    # route cut to a default nobody chose.
    And STDERR should contain "'cam:' does not take toool"

  @success @pc-cam
  Scenario: An implementation nothing declares is a configuration to correct
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
          cam:
            tool: 6 mm
            implementation: //nowhere:gcode
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi cam"
    Then the command should exit with a status code of "1"
    And STDERR should contain "The package implementing 'cam' is not found"

  @success @pc-cam @pc-test
  Scenario: `pc test -f cam` is the route check and applies only where `cam:` is declared
    # The check that used to answer to this name is `manufacturability` now.
    # This one produces the route and sees whether one comes back, so a package
    # that declares no `cam:` anywhere pays nothing for it -- which is what this
    # scenario is: no geometry is built, and the run is seconds.
    Given a file named "partcad.yaml" with content:
      """
      parts:
        panel:
          type: build123d
          path: panel.py
          cam:
            toool: 3 mm
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi test -f cam"
    Then the command should exit with a status code of "1"
    And STDERR should contain "cam: 'cam:' does not take toool"

  @success @pc-cam @pc-test
  Scenario: A slash in an object's name is a directory the route check makes for itself
    # A package of machined plates groups them -- `cnc/flange` -- and the route
    # is named after the object, so the check's own temporary directory needs a
    # subdirectory for it. `--create-dirs` is about the user's output tree and
    # there is no `-p` on `pc test`, so without the check making it, every
    # grouped object failed on a missing file rather than on its route.
    Given a file named "partcad.yaml" with content:
      """
      parts:
        cnc/panel:
          type: build123d
          path: panel.py
          cam:
            tool: 3 mm
            feed: 600 mm/min
            plunge: 200 mm/min
            safe_z: 5 mm
            depth_per_pass: 2 mm
      """
    And a file named "panel.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(40, 30, 6)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="panel")
      """
    When I run "pc --no-ansi test -f cam"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "No such file or directory"
