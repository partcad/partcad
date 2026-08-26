const { defineConfig } = require('@vscode/test-cli');

// TODO: Deal with GPU errors: https://github.com/microsoft/vscode-test-cli/issues/61

module.exports = defineConfig([
  {
    label: 'unitTests',
    files: 'out/test/**/*.test.js',
    launchArgs: ['--disable-gpu'],
    // version: 'insiders', // For some reason this doesn't work
    workspaceFolder: './sampleWorkspace',
    mocha: {
      ui: 'tdd',
      // Activation starts the Python language server, so this budget is really
      // "how long a cold LSP start takes on a loaded runner" rather than
      // anything about the assertion. It went 20s -> 30s once already for the
      // same reason, and 30s started failing about two runs in three (the same
      // commit passed and failed), so it is marginal rather than broken.
      // Doubled to stop trimming it by 50% every time the runners get busier;
      // if activation ever genuinely hangs, 60s still fails the run.
      timeout: 60000,
    },
  },
]);
