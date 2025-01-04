@cli @pc-config
Feature: `pc config` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-config
  Scenario: Override user configurations with env. variables
    Given a user configuration file named "config.yaml" with content:
      """
      threadsMax: 5555
      ollamaNumThread: 9999
      maxScriptCorrection: 6666
      maxModelGeneration: 7777
      maxGeometricModeling: 8888
      openaiApiKey: "1234567890"
      googleApiKey: "0987654321"
      forceUpdate: true
      internalStateDir: "/other_temp/sandbox/home/.partcad"
      pythonSandbox: "conda"
      """
    When I run "PC_THREADSMAX=1234 PC_OLLAMANUMTHREAD=5678 PC_MAXSCRIPTCORRECTION=4321 PC_MAXMODELGENERATION=8765 PC_MAXGEOMETRICMODELING=3456 PC_PYTHONSANDBOX=pypy PC_FORCEUPDATE=false pc config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "threads_max: 1234"
    And STDOUT should contain "ollama_num_thread: 5678"
    And STDOUT should contain "max_script_correction: 4321"
    And STDOUT should contain "max_model_generation: 8765"
    And STDOUT should contain "max_geometric_modeling: 3456"
    And STDOUT should contain "python_runtime: pypy"
    And STDOUT should contain "force_update: False"


  @success @pc-config
  Scenario: set cli options with environment variable
    When I run "PC_VERBOSE=1 pc config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "DEBUG:"
