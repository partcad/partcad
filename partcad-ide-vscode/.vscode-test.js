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
      timeout: 20000,
    },
  },
]);
