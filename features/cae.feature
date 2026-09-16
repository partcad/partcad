@cli @pc-cae
Feature: `pc cae` command

  `pc cae fea` and `pc cae cfd` put a part's own question to a solver. The part
  says what holds it and what it carries, in a section named after the analysis,
  because that is a property of the part rather than of whoever analyses it.
  PartCAD ships no solver: the implementation is a package, declared in a `cae:`
  section exactly as an export or a render implementation is declared in its own.

  That last fact is what this feature is built around. Nothing here installs
  CalculiX or reaches the index -- the package under test declares an
  implementation **of its own**, which is a supported way to write one and the
  only way to exercise the whole path without a solver, a network and a
  container runtime.

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  # ------------------------------------------------------------------------ #
  # The one scenario that builds geometry                                     #
  # ------------------------------------------------------------------------ #

  # Every scenario gets a `$HOME` of its own, so every scenario that builds a
  # shape builds a CAD sandbox from nothing. There is exactly one of those here,
  # and it asks everything that needs a real run in one go: the later `When I
  # run` steps share the sandbox the first one paid for.
  @success @pc-cae @pc-cae-analyze
  Scenario: A part's boundary conditions reach the implementation, and its findings come back
    Given a file named "partcad.yaml" with content:
      """
      # Pinned because the implementation below runs through the same sandbox
      # the part is built in, and the meta-wrapper that starts it imports OCP.
      # An implementation that declared nothing would be run in a bare
      # interpreter and would fail on that import rather than on anything about
      # this test. These are the versions `partcad.sandbox_versions` pins.
      pythonRequirements:
        - build123d==0.11.1
        - cadquery-ocp==7.9.3.1.1

      interfaces:
        anchor:
          ports:
            root:

      parts:
        bracket:
          type: build123d
          path: bracket.py
          implements:
            anchor: [[-20, 0, 0], [0, 0, 1], 0]
          fea:
            # ':fea' is this package's own `cae: fea:` below. A part naming its
            # own implementation is the documented way to say which solver it
            # was written against, and here it is what removes the network.
            implementation: ":fea"
            fix:
              - anchor
            load:
              anchor: 5 kg
      cae:
        fea:
          path: solve.py
          extension: txt
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(40, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    And a file named "solve.py" with content:
      """
      import json


      def process(path, request):
          # A real solver would mesh and solve. This writes down what crossed
          # into the sandbox instead, so the test can hold the plumbing to what
          # it promised: which analysis, what the part declared, and where the
          # conditions landed.
          #
          # Written as plain `key=value` lines rather than as JSON because the
          # step that reads a file back takes its needle in double quotes, and
          # behave does not read backslash escapes inside a step argument.
          boundary = request.get("boundary") or []
          with open(path, "w") as model:
              model.write("analysis=%s\n" % request.get("analysis"))
              model.write("fix=%s\n" % json.dumps(request.get("fix"), sort_keys=True))
              model.write("load=%s\n" % json.dumps(request.get("load"), sort_keys=True))
              model.write("ports=%d\n" % len(boundary))
              for record in boundary:
                  model.write("port=%s/%s\n" % (record.get("interface"), record.get("instance") or ""))
          return {"success": True, "exception": None, "findings": []}
      """
    When I run "pc --no-ansi cae fea :bracket"
    # No findings is a pass, and a pass exits 0 so the command can gate a script.
    Then the command should exit with a status code of "0"
    # Named after the analysis as well as the object: a part has as many results
    # as it has analyses, so 'bracket.json' would be the wrong name.
    And a file named "bracket.fea.txt" should be created
    And STDERR should contain "FEA found nothing to report"
    # Which analysis the implementation was run for: the file type is called
    # `fea` here too, but what decides this is the command that was run.
    And a file named "bracket.fea.txt" should contain "analysis=fea"
    # What the part declared, converted. A bare number is a mass in kilograms
    # and is weighed into newtons at 9.8 N/kg, so `5 kg` arrives as 49.0 and not
    # as 5 -- the one step of this plumbing that silently changes a number.
    And a file named "bracket.fea.txt" should contain "49.0"
    # And where the conditions landed: the part names an interface, and a solver
    # needs a coordinate frame, so PartCAD resolves one into the other with the
    # very lookup `pc render --with-ports` draws.
    And a file named "bracket.fea.txt" should contain "ports=1"
    And a file named "bracket.fea.txt" should contain "port=//:anchor"
    # `--json` prints the findings array itself, for whatever comes next. A
    # clean run prints `[]` rather than the numbers.
    When I run "pc --no-ansi cae fea --json :bracket"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "[]"
    # The same part, asked the other question. It declares no `cfd:` section, so
    # there is nothing to analyse and saying so is the answer.
    When I run "pc --no-ansi cae cfd :bracket"
    Then the command should exit with a status code of "2"
    And STDERR should contain "declares no 'cfd:' section"

  # ------------------------------------------------------------------------ #
  # Everything below is settled by the declaration alone                      #
  # ------------------------------------------------------------------------ #

  # `Shape.analyze_async()` reads the part's own section before it asks for the
  # shape or for a solver, so a section that cannot be read costs no geometry
  # and no sandbox at all. That is what makes these cheap enough to have.

  @success @pc-cae
  Scenario: A part that declares nothing is told so rather than analysed
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi cae fea :bracket"
    # A usage error, because it is the user's question that does not apply
    # rather than the machinery failing.
    Then the command should exit with a status code of "2"
    And STDERR should contain "declares no 'fea:' section, so there is nothing to analyse"

  @success @pc-cae
  Scenario: A section that declares neither `fix:` nor `load:` is not a boundary condition
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
          fea:
            desc: A section that says nothing a solver can be told
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi cae fea :bracket"
    Then the command should exit with a status code of "2"
    And STDERR should contain "declares neither 'fix:' nor 'load:'"

  @success @pc-cae
  Scenario: A key `fea:` does not take is refused rather than passed to a solver
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
          fea:
            fix: [anchor]
            outlet: [anchor]
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi cae fea :bracket"
    Then the command should exit with a status code of "2"
    # `outlet:` is CFD's and only CFD's: a stress analysis has nothing to let
    # out, and accepting the word here would let a part say something that reads
    # as a boundary condition and is not one.
    And STDERR should contain "'fea:' does not take outlet"

  @success @pc-cae
  Scenario: A load that is neither a force nor a mass is refused, naming what it may be
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
          fea:
            fix: [anchor]
            load:
              hook: quite a lot
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi cae fea :bracket"
    Then the command should exit with a status code of "2"
    And STDERR should contain "is not a force or a mass"

  @success @pc-cae
  Scenario: An implementation nothing declares is a configuration to correct
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
          fea:
            implementation: //nowhere:fea
            fix: [anchor]
            load:
              hook: 5 kg
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi cae fea :bracket"
    Then the command should exit with a status code of "1"
    And STDERR should contain "The package implementing 'fea' is not found"

  @success @pc-cae @pc-test
  Scenario: `pc test -f fea` applies only to a part that declares the section
    # The gate is the whole cost model: a `pc test -r` over a package tree must
    # not start a solver for every bolt in it. This package declares no `fea:`
    # anywhere, so the check is not applicable, nothing is built, and the run is
    # seconds rather than minutes.
    Given a file named "partcad.yaml" with content:
      """
      parts:
        bracket:
          type: build123d
          path: bracket.py
      """
    And a file named "bracket.py" with content:
      """
      import build123d as bd

      with bd.BuildPart() as result:
          bd.Box(10, 10, 10)

      if "show_object" in locals():
          show_object(result.part.wrapped, name="bracket")
      """
    When I run "pc --no-ansi test -f fea"
    Then the command should exit with a status code of "0"
