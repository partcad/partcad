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
      // Extension activation exceeded the previous 20s budget on the current
      // CI runners. Raised once by 50% to see whether the runners are simply
      // slower than they used to be.
      timeout: 30000,
    },
  },
]);
