@cli @pc-render
Feature: `pc render` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"

  @docs-tutorial
  Scenario: Tutorial
    When I run "pc init -p"
    Then the command should exit with a status code of "0"
    When a file named "partcad.yaml" is written with content:
      """
      dependencies:
        # Public PartCAD repository (reference it explicitly if required)
        pub:
          type: git
          url: https://github.com/partcad/partcad-index.git
      """
    And I run "pc list"
    Then the command should exit with a status code of "0"
    When I run "echo "translate (v= [0,0,0])  cube (size = 10);" > test.scad"
    Then the command should exit with a status code of "0"
    When I run "pc add part scad test.scad"
    Then the command should exit with a status code of "0"
    When I run "pc inspect :test"
    Then the command should exit with a status code of "0"
    When I run "pc export -t stl :test"
    Then the command should exit with a status code of "0"
    # TODO: Add more asserts
    # And STDOUT should contain "Rendering STL file"
    # And the file "test.stl" should exist



  @wip @docs-design
  Scenario: Design: Parametrized objects
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run command:
      """
      pc \
        inspect \
          -p length=30 \
          -p size=M4-0.7 \
          //pub/std/metric/cqwarehouse:fastener/hexhead-din931
      """
    # TODO: Failure to pip install from GH repo
    Then the command should exit with a status code of "0"
    When I run command:
      """
      pc \
        inspect \
          //pub/std/metric/cqwarehouse:fastener/hexhead-din931;length=30,size=M4-0.7
      """
    Then the command should exit with a status code of "0"
     And STDOUT should contain 'DONE: InitCtx:'
     And STDOUT should contain 'Visualizing in "OCP CAD Viewer"...'
     And STDOUT should contain 'Unable to open config file /tmp/sandbox/home/partcad-cli-'
     And STDOUT should contain 'No VS Code or "OCP CAD Viewer" extension detected.'
     And STDOUT should contain 'DONE: inspect: this'

  @wip @docs-design @pc-241
  Scenario: Design: Objects in a cart
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run command:
      """
      pc supply quote \
        --provider //pub/svc/commerce/gobilda:gobilda \
        //pub/robotics/multimodal/openvmp/robots/don1:assembly-wormgear#10
      """
    # TODO: We don't have enough XXX stock on hand for the quantity you selected
    # @alexanderilyin: Well... now I start thinking that during tests we don't really need to go to the live provider
    # and can get avail with simple local HTTP mock (could be started as python script). This will make those tests
    # reproducible, fast and wont lead to billing.
    Then the command should exit with a status code of "1"
     And STDOUT should contain 'DONE: SupplyQuote: this:'
     And STDOUT should contain 'The following quotes are received:'
     And STDOUT should contain '//pub/svc/commerce/gobilda:gobilda: No quote received'

  # TODO: This depends on ~/.partcad/config.yaml:googleApiKey
  # @alexanderilyin: I'm still not sure if it's okay to use live 3rd parties services during PR checks but from other
  # had if it does not work in PRs for any reason same will happen for end user, so IMHO best part here is to have
  # dedicated GitHub Actions token with spending limit.
  @wip @docs-features
  Scenario: Features: Design
    When I run command:
      """
      mkdir -pv $HOME/.partcad
      """
    Then the command should exit with a status code of "0"
    When a file named "$HOME/.partcad/config.yaml" is written with content:
      """
      # https://aistudio.google.com/apikey
      # TODO: Create dedicated token for CI and create version of test for success scenario
      googleApiKey: $PARTCAD_GOOGLE_API_KEY_MISSING
      # YOLO settings to speed up the process
      maxGeometricModeling: 1
      maxModelGeneration: 1
      maxScriptCorrection: 1
      """
    And I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc add part ai-openscad --ai google --desc 'Pixel phone case of a surprising shape' 'generated-case.scad'"
    Then the command should exit with a status code of "0"
    When I run "pc inspect 'generated-case'"
    Then the command should exit with a status code of "0"
     And STDOUT should contain "DONE: InitCtx: /tmp/sandbox/behave/partcad-cli-"
     # TODO: This could be moved to it's own test for negative scenario.
     # And STDOUT should contain "Failed to generate with Google: Google API key is not set"
     # And STDOUT should contain "Generated 0 CSG modeling candidates"
     # And STDOUT should contain "No valid script generated. Try changing the prompt."
     # And STDOUT should contain "OpenSCAD script is empty or does not exist: /tmp/sandbox/behave/partcad-cli-"
    When I run "true > 'generated-case.scad'"
    Then the command should exit with a status code of "0"
    When I run "pc inspect 'generated-case'"
    Then the command should exit with a status code of "0"


  # TODO: This depends on ~/.partcad/config.yaml:googleApiKey
  @wip @docs-features
  Scenario: Features: Summarization
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc inspect -V //pub/robotics/parts/gobilda:structure/u_channel_2"
    Then the command should exit with a status code of "0"
    When I run "pc inspect -V -a //pub/robotics/parts/gobilda:examples/wormgear"
    Then the command should exit with a status code of "0"

  # TODO: This depends on ~/.partcad/config.yaml:googleApiKey
  @wip @docs-features
  Scenario: Features: Summarization (Script Friendly)
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc -q --no-ansi inspect -V //pub/robotics/parts/gobilda:structure/u_channel_2"
    Then the command should exit with a status code of "0"
    When I run "pc -q --no-ansi inspect -V -a //pub/robotics/parts/gobilda:examples/wormgear"
    Then the command should exit with a status code of "0"

  @docs-installation
  Scenario: Installation: Command line tools
    When I run "pc --help"
    Then the command should exit with a status code of "0"
    When I run "pc status"
    Then the command should exit with a status code of "0"

  # TODO: Failure to pip install from GH repo
  @wip @docs-troubleshooting
  Scenario: Troubleshooting: Command Line
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc inspect //pub/std/metric/cqwarehouse:fastener/hexhead-iso4014"
    Then the command should exit with a status code of "0"

  @docs-use-cases
  Scenario: Troubleshooting: Command Line
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run "pc list"
    Then the command should exit with a status code of "0"
    When I run "pc list sketches -r"
    Then the command should exit with a status code of "0"
    When I run "pc list interfaces -r"
    Then the command should exit with a status code of "0"
    # TODO: TypeError: startswith first arg must be str or a tuple of str, not Project
    # When I run "pc list mates -r"
    # Then the command should exit with a status code of "0"
    When I run "pc list parts -r"
    Then the command should exit with a status code of "0"
    When I run "pc list assemblies -r"
    Then the command should exit with a status code of "0"
    # TODO Failure to pip install from GH repo
    # When I run "pc info //pub/std/metric/cqwarehouse:fastener/hexhead-din931"
    # Then the command should exit with a status code of "0"
    # When I run "pc inspect //pub/std/metric/cqwarehouse:fastener/hexhead-din931"
    # Then the command should exit with a status code of "0"
    # When I run command:
    #   """
    #   pc \
    #     inspect \
    #       -p length=30 \
    #       -p size=M4-0.7 \
    #       //pub/std/metric/cqwarehouse:fastener/hexhead-din931
    #   """
    # Then the command should exit with a status code of "0"
    When I run "pc export -t stl //pub/robotics/parts/gobilda:structure/u_channel_2"
    Then the command should exit with a status code of "0"
    When I run "pc export -t step -a //pub/robotics/parts/gobilda:examples/wormgear"
    Then the command should exit with a status code of "0"
    When I run "pc export -P //pub/robotics/parts/gobilda -t stl structure/u_channel_2"
    Then the command should exit with a status code of "0"
    When I run "pc export -P //pub/robotics/parts/gobilda -t step -a examples/wormgear"
    Then the command should exit with a status code of "0"
    When I run "pc render -t png //pub/robotics/parts/gobilda:structure/u_channel_2"
    Then the command should exit with a status code of "0"
    When I run "pc render -t png -a //pub/robotics/parts/gobilda:examples/wormgear"
    Then the command should exit with a status code of "0"
