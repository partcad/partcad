@cli @pc-config
Feature: `pc config` command

  Background: Create temporary $HOME and working directory
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @success @pc-config
  Scenario: Override config.yaml with environment variables
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
      cacheFiles: false
      cacheFilesMaxEntrySize: 100
      cacheFilesMinEntrySize: 10
      cacheMemoryMaxEntrySize: 100
      cacheMemoryDoubleCacheMaxEntrySize: 100
      cacheDependenciesIgnore: false
      sentry:
          debug: true
          shutdown_timeout: 20
          traces_sample_rate: 1.0
      """
    And environment variable "PC_THREADS_MAX" is set to "1234"
    And environment variable "PC_OLLAMA_NUM_THREAD" is set to "5678"
    And environment variable "PC_MAX_SCRIPT_CORRECTION" is set to "4321"
    And environment variable "PC_MAX_MODEL_GENERATION" is set to "8765"
    And environment variable "PC_MAX_GEOMETRIC_MODELING" is set to "3456"
    And environment variable "PC_OPENAI_API_KEY" is set to "abcdef12345"
    And environment variable "PC_GOOGLE_API_KEY" is set to "fedcba54321"
    And environment variable "PC_INTERNAL_STATE_DIR" is set to "/tmp/sandbox/home/.partcad"
    And environment variable "PC_PYTHON_SANDBOX" is set to "pypy"
    And environment variable "PC_FORCE_UPDATE" is set to "false"
    And environment variable "PC_CACHE_FILES" is set to "true"
    And environment variable "PC_CACHE_FILES_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_FILES_MIN_ENTRY_SIZE" is set to "11"
    And environment variable "PC_CACHE_MEMORY_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_DEPENDENCIES_IGNORE" is set to "true"
    And environment variable "PC_SENTRY_DEBUG" is set to "false"
    And environment variable "PC_SENTRY_TRACES_SAMPLE_RATE" is set to "0.55"
    And environment variable "PC_SENTRY_SHUTDOWN_TIMEOUT" is set to "11"
    When I run "pc config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "threads_max: 1234"
    And STDOUT should contain "ollama_num_thread: 5678"
    And STDOUT should contain "max_script_correction: 4321"
    And STDOUT should contain "max_model_generation: 8765"
    And STDOUT should contain "max_geometric_modeling: 3456"
    And STDOUT should contain "openai_api_key: abcdef12345"
    And STDOUT should contain "google_api_key: fedcba54321"
    And STDOUT should contain "internal_state_dir: /tmp/sandbox/home/.partcad"
    And STDOUT should contain "python_sandbox: pypy"
    And STDOUT should contain "force_update: False"
    And STDOUT should contain "cache: True"
    And STDOUT should contain "cache_max_entry_size: 101"
    And STDOUT should contain "cache_min_entry_size: 11"
    And STDOUT should contain "cache_memory_max_entry_size: 101"
    And STDOUT should contain "cache_memory_double_cache_max_entry_size: 101"
    And STDOUT should contain "cache_dependencies_ignore: True"
    And STDOUT should contain "sentry_config: {'debug': False, 'shutdown_timeout': 11, 'traces_sample_rate': 0.55}"

  @success @pc-config
  Scenario: Override CLI options with environment variables
    And environment variable "PC_THREADS_MAX" is set to "1234"
    And environment variable "PC_OLLAMA_NUM_THREAD" is set to "5678"
    And environment variable "PC_MAX_SCRIPT_CORRECTION" is set to "4321"
    And environment variable "PC_MAX_MODEL_GENERATION" is set to "8765"
    And environment variable "PC_MAX_GEOMETRIC_MODELING" is set to "3456"
    And environment variable "PC_OPENAI_API_KEY" is set to "abcdef12345"
    And environment variable "PC_GOOGLE_API_KEY" is set to "fedcba54321"
    And environment variable "PC_INTERNAL_STATE_DIR" is set to "/tmp/sandbox/home/.partcad"
    And environment variable "PC_PYTHON_SANDBOX" is set to "conda"
    And environment variable "PC_FORCE_UPDATE" is set to "false"
    And environment variable "PC_CACHE_FILES" is set to "false"
    And environment variable "PC_CACHE_FILES_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_FILES_MIN_ENTRY_SIZE" is set to "11"
    And environment variable "PC_CACHE_MEMORY_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_DEPENDENCIES_IGNORE" is set to "false"
    And environment variable "PC_SENTRY_DEBUG" is set to "false"
    And environment variable "PC_SENTRY_TRACES_SAMPLE_RATE" is set to "0.55"
    And environment variable "PC_SENTRY_SHUTDOWN_TIMEOUT" is set to "11"
    When I run "pc --threads-max=1111 --ollama-num-thread=2222 --max-script-correction=3333 --max-model-generation=4444 --max-geometric-modeling=5555 --openai-api-key=notused --google-api-key=notused --internal-state-dir=/not/used --python-sandbox=pypy --force-update --cache --cache-max-entry-size=102 --cache-min-entry-size=12 --cache-memory-max-entry-size=102 --cache-memory-double-cache-max-entry-size=102 --cache-dependencies-ignore --sentry-debug --sentry-traces-sample-rate=0.3 --sentry-shutdown-timeout=200 config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "threads_max: 1234"
    And STDOUT should contain "ollama_num_thread: 5678"
    And STDOUT should contain "max_script_correction: 4321"
    And STDOUT should contain "max_model_generation: 8765"
    And STDOUT should contain "max_geometric_modeling: 3456"
    And STDOUT should contain "openai_api_key: abcdef12345"
    And STDOUT should contain "google_api_key: fedcba54321"
    And STDOUT should contain "internal_state_dir: /tmp/sandbox/home/.partcad"
    And STDOUT should contain "python_sandbox: conda"
    And STDOUT should contain "force_update: False"
    And STDOUT should contain "cache: False"
    And STDOUT should contain "cache_max_entry_size: 101"
    And STDOUT should contain "cache_min_entry_size: 11"
    And STDOUT should contain "cache_memory_max_entry_size: 101"
    And STDOUT should contain "cache_memory_double_cache_max_entry_size: 101"
    And STDOUT should contain "cache_dependencies_ignore: False"
    And STDOUT should contain "sentry_config: {'debug': False, 'shutdown_timeout': 35, 'traces_sample_rate': 0.65}"

  @success @pc-config
  Scenario: Override config.yaml with CLI options
    Given a user configuration file named "config.yaml" with content:
      """
      threadsMax: 5555
      ollamaNumThread: 9999
      maxScriptCorrection: 6666
      maxModelGeneration: 7777
      maxGeometricModeling: 8888
      openaiApiKey: "1234567890"
      googleApiKey: "0987654321"
      forceUpdate: false
      internalStateDir: "/other_temp/sandbox/home/.partcad"
      pythonSandbox: "conda"
      cacheFiles: false
      cacheFilesMaxEntrySize: 100
      cacheFilesMinEntrySize: 10
      cacheMemoryMaxEntrySize: 100
      cacheMemoryDoubleCacheMaxEntrySize: 100
      cacheDependenciesIgnore: true
      sentry:
          debug: false
          shutdown_timeout: 14
          traces_sample_rate: 0.43
      """
    When I run "pc --threads-max=1111 --ollama-num-thread=2222 --max-script-correction=3333 --max-model-generation=4444 --max-geometric-modeling=5555 --openai-api-key=abcdef12345 --google-api-key=fedcba54321 --internal-state-dir=/tmp/sandbox/home/.partcad --python-sandbox=pypy --force-update --cache --cache-max-entry-size=102 --cache-min-entry-size=12 --cache-memory-max-entry-size=102 --cache-memory-double-cache-max-entry-size=102 --cache-dependencies-ignore --sentry-debug --sentry-traces-sample-rate=0.35 --sentry-shutdown-timeout=44 config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "threads_max: 1111"
    And STDOUT should contain "ollama_num_thread: 2222"
    And STDOUT should contain "max_script_correction: 3333"
    And STDOUT should contain "max_model_generation: 4444"
    And STDOUT should contain "max_geometric_modeling: 5555"
    And STDOUT should contain "openai_api_key: abcdef12345"
    And STDOUT should contain "google_api_key: fedcba54321"
    And STDOUT should contain "internal_state_dir: /tmp/sandbox/home/.partcad"
    And STDOUT should contain "python_sandbox: pypy"
    And STDOUT should contain "force_update: True"
    And STDOUT should contain "cache: True"
    And STDOUT should contain "cache_max_entry_size: 102"
    And STDOUT should contain "cache_min_entry_size: 12"
    And STDOUT should contain "cache_memory_max_entry_size: 102"
    And STDOUT should contain "cache_memory_double_cache_max_entry_size: 102"
    And STDOUT should contain "cache_dependencies_ignore: True"
    And STDOUT should contain "sentry_config: {'debug': True, 'shutdown_timeout': 44, 'traces_sample_rate': 0.35}"

  @success @pc-config
  Scenario: Environment variables should have the highest precedence
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
      cacheFiles: false
      cacheFilesMaxEntrySize: 100
      cacheFilesMinEntrySize: 10
      cacheMemoryMaxEntrySize: 100
      cacheMemoryDoubleCacheMaxEntrySize: 100
      cacheDependenciesIgnore: false
      sentry:
          debug: true
          shutdown_timeout: 64
          traces_sample_rate: 0.25
      """
    And environment variable "PC_THREADS_MAX" is set to "1234"
    And environment variable "PC_OLLAMA_NUM_THREAD" is set to "5678"
    And environment variable "PC_MAX_SCRIPT_CORRECTION" is set to "4321"
    And environment variable "PC_MAX_MODEL_GENERATION" is set to "8765"
    And environment variable "PC_MAX_GEOMETRIC_MODELING" is set to "3456"
    And environment variable "PC_OPENAI_API_KEY" is set to "abcdef12345"
    And environment variable "PC_GOOGLE_API_KEY" is set to "fedcba54321"
    And environment variable "PC_INTERNAL_STATE_DIR" is set to "/tmp/sandbox/home/.partcad"
    And environment variable "PC_PYTHON_SANDBOX" is set to "pypy"
    And environment variable "PC_FORCE_UPDATE" is set to "false"
    And environment variable "PC_CACHE_FILES" is set to "true"
    And environment variable "PC_CACHE_FILES_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_FILES_MIN_ENTRY_SIZE" is set to "11"
    And environment variable "PC_CACHE_MEMORY_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE" is set to "101"
    And environment variable "PC_CACHE_DEPENDENCIES_IGNORE" is set to "true"
    And environment variable "PC_SENTRY_DEBUG" is set to "false"
    And environment variable "PC_SENTRY_TRACES_SAMPLE_RATE" is set to "0.55"
    And environment variable "PC_SENTRY_SHUTDOWN_TIMEOUT" is set to "11"
    When I run "pc --threads-max=1111 --ollama-num-thread=2222 --max-script-correction=3333 --max-model-generation=4444 --max-geometric-modeling=5555 --openai-api-key=notused --google-api-key=notused --internal-state-dir=/not/used --python-sandbox=none --force-update --cache-max-entry-size=102 --cache-min-entry-size=12 --cache-memory-max-entry-size=102 --cache-memory-double-cache-max-entry-size=102 --sentry-debug --sentry-traces-sample-rate=0.35 --sentry-shutdown-timeout=44 config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "threads_max: 1234"
    And STDOUT should contain "ollama_num_thread: 5678"
    And STDOUT should contain "max_script_correction: 4321"
    And STDOUT should contain "max_model_generation: 8765"
    And STDOUT should contain "max_geometric_modeling: 3456"
    And STDOUT should contain "openai_api_key: abcdef12345"
    And STDOUT should contain "google_api_key: fedcba54321"
    And STDOUT should contain "internal_state_dir: /tmp/sandbox/home/.partcad"
    And STDOUT should contain "python_sandbox: pypy"
    And STDOUT should contain "force_update: False"
    And STDOUT should contain "cache: True"
    And STDOUT should contain "cache_max_entry_size: 101"
    And STDOUT should contain "cache_min_entry_size: 11"
    And STDOUT should contain "cache_memory_max_entry_size: 101"
    And STDOUT should contain "cache_memory_double_cache_max_entry_size: 101"
    And STDOUT should contain "cache_dependencies_ignore: True"
    And STDOUT should contain "sentry_config: {'debug': False, 'shutdown_timeout': 12, 'traces_sample_rate': 0.75}"

  @success @pc-config
  Scenario: set cli options with environment variable
    Given environment variable "PC_VERBOSE" is set to "1"
    When I run "pc config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "DEBUG:"
