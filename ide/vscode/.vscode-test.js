const { defineConfig } = require('@vscode/test-cli');

// TODO: Deal with GPU errors: https://github.com/microsoft/vscode-test-cli/issues/61

module.exports = defineConfig([
  {
    label: 'unitTests',
    files: 'out/test/**/*.test.js',
    launchArgs: ['--disable-gpu'],
    // version: 'insiders', // For some reason this doesn't work
    workspaceFolder: './sampleWorkspace',
    // No PartCAD is installed on a CI runner, so activation reaches the "shall I
    // download it?" dialog. Nothing in a headless run can answer a modal dialog,
    // and on Windows an unanswered one is enough to keep the window from ever
    // closing -- which is what "windows-latest doesn't run the test suite" was.
    env: { PARTCAD_EXTENSION_NO_PROMPTS: '1' },
    mocha: {
      ui: 'tdd',
      // This budget is "how long activation takes on a loaded runner" rather
      // than anything about the assertions. It went 20s -> 30s once, and 30s
      // then started failing about two runs in three (the same commit passing
      // and failing), so it is marginal rather than broken. Doubled to stop
      // trimming it by 50% every time the runners get busier; if activation
      // ever genuinely hangs, 60s still fails the run.
      timeout: 60000,
    },
  },
]);
