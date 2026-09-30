@cli
Feature: `pc system status` command

  Background: Initialize Private PartCAD project
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-init @pc-status @success
  Scenario: Show subsystems status
    When I run "partcad system status"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PartCAD version:"
    And STDOUT should contain "Internal data storage location: $HOME/.partcad" with path
    And STDOUT should match the regex "Tar cache size: \d\.\d+[KMGT]B"
    And STDOUT should match the regex "Git cache size: \d\.\d+[KMGT]B"
    And STDOUT should contain "Sandbox environments size:"
    And STDOUT should contain "Conda package cache size:"
    And STDOUT should contain "Total internal data storage size:"
    And STDOUT should contain "DONE: Status: global:"

  @pc-status @success
  Scenario: Dump the configuration this installation resolved
    Given environment variable "PC_THREADS_MAX" is set to "1234"
    And environment variable "PC_REMOTE_SANDBOX_TOKEN" is set to "s3cr3t-do-not-print"
    When I run "partcad system status config"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Configuration file: $HOME/.partcad/config.yaml" with path
    And STDOUT should contain "threads_max: 1234"
    # The report is what people paste into bug reports, so a shared secret that
    # runs commands on another machine says only whether it is configured.
    And STDOUT should contain "remote_sandbox_token: <set>"
    And STDOUT should not contain "s3cr3t-do-not-print"
    And STDOUT should contain "DONE: StatusConfig: global:"

  @pc-status @success
  Scenario: Dump the PC_* environment this process was started with
    Given environment variable "PC_TAGS" is set to "build-machine"
    And environment variable "PC_REMOTE_SANDBOX_TOKEN" is set to "s3cr3t-do-not-print"
    When I run "partcad system status env"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "PC_TAGS=build-machine"
    # Named, so that "is it set" is answerable; never printed.
    And STDOUT should contain "PC_REMOTE_SANDBOX_TOKEN=<scrubbed>"
    And STDOUT should not contain "s3cr3t-do-not-print"
    And STDOUT should contain "DONE: StatusEnv: global:"

  @wip
  Scenario: Show status with corrupted cache
    Given the cache directory is corrupted
    When I run "partcad system status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Cache integrity check failed"

  @wip
  Scenario: Show status with insufficient permissions
    Given I have insufficient permissions for "$HOME/.partcad"
    When I run "partcad system status"
    Then the command should exit with a non-zero status code
    And STDOUT should contain "Permission denied"
