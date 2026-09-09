@cli
Feature: `pc init` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-init
  Scenario: Initialize new package as public
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "PartCAD configuration file is not found"
    And a file named "partcad.yaml" should have YAML content:
      """
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
        pub:
          type: git
          url: https://github.com/partcad/partcad-index.git
          revision: main
      sketches:
      parts:
      assemblies:
      """

  @pc-init @private
  Scenario: Initialize new package as private
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      """
    And the package should be marked as private

  @pc-init @launch-configuration
  Scenario: Add the "Render" command to the editor's launch configuration
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named ".vscode/launch.json" should be created
    And the file ".vscode/launch.json" should hold the "Render" run command
    And STDERR should contain "Added the 'Render' command"

  @pc-init @agent-skills
  Scenario: Install the AI agent skills the repository's agent will need
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    # Claude Code gets the plugin, which is what puts the skills in one
    # namespace: "/pc:init" rather than "/init".
    And a file named ".claude/skills/pc/.claude-plugin/plugin.json" should be created
    And a file named ".claude/skills/pc/skills/init/SKILL.md" should be created
    # Cursor has no plugin, so the prefix is the namespace.
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And a file named ".cursor/skills/init/SKILL.md" should not exist
    And the skill "pc-init" should be named after its directory
    And STDERR should contain "Installed the 'pc' plugin"

  @pc-init @agent-skills @skills-only
  Scenario: Install the skills into a repository that has a package already
    # The package this would have created exists, which is the usual reason to
    # want this: the skills came from the "pc init" that created it, and a newer
    # PartCAD has newer ones.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi init --skills-only"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "File already exists"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created

  @pc-init @agent-skills @skills-only
  Scenario: Install the skills where there is no package at all
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --skills-only"
    Then the command should exit with a status code of "0"
    And a file named ".claude/skills/pc/.claude-plugin/plugin.json" should be created
    And a file named "partcad.yaml" should not exist
    And a file named ".vscode/launch.json" should not exist

  @pc-init @agent-skills @skills-only @failure
  Scenario: Ask for the skills and for no skills at once
    When I run "pc --no-ansi init --skills-only --no-skills"
    Then the command should exit with a status code of "1"
    And STDERR should contain "ask for opposite things"
    And a directory named ".cursor" should not exist

  @pc-init @agent-skills
  Scenario: Create a package without them
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --no-skills"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    And a directory named ".claude" should not exist
    And a directory named ".cursor" should not exist

  @pc-init @option-private @failure
  Scenario: Fail initializing package when `partcad.yaml`already exists
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then a file named "partcad.yaml" should be created
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "1"
    And STDERR should contain "File already exists: partcad.yaml"
    And STDERR should contain "Failed creating 'partcad.yaml'!"

  @wip @pc-init @failure
  Scenario: Fail initializing package with insufficient permissions
    Given I am in "/tmp/sandbox/behave" directory
    And the directory has read-only permissions
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Permission denied"

  @wip @pc-init @failure
  Scenario: Fail initializing with malformed existing YAML
    Given a file named "partcad.yaml" with content:
      """
      invalid:
        - yaml:
      content:
      """
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid YAML format"
