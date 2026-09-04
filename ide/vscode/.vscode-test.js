const { defineConfig } = require('@vscode/test-cli');

// TODO: Deal with GPU errors: https://github.com/microsoft/vscode-test-cli/issues/61

// The built PartCAD IDE to run against, if there is one: the path of the
// application *binary*, not of the bundle or the `bin/` launcher.
//
// `unitTests` below downloads stock VS Code, which is right for what it checks
// -- this extension's own logic -- and blind to everything the IDE puts around
// it: the built-in extension set, `product.json`'s `configurationDefaults`, the
// bootstrap extension, the embedded `partcad-json-rpc`, and the branded
// application shell. Nothing in this repository used to start the editor that
// ships. The macOS bundle could not start at all for two releases and no test
// here could have noticed.
//
// Set by `.github/workflows/build-ide-standalone.yml` after it installs a
// build. Unset locally, where there is usually no bundle to point at, and then
// this configuration is simply not offered.
const bundledIde = process.env.PARTCAD_IDE_PATH;

const mocha = {
  ui: 'tdd',
  // This budget is "how long activation takes on a loaded runner" rather
  // than anything about the assertions. It went 20s -> 30s once, and 30s
  // then started failing about two runs in three (the same commit passing
  // and failing), so it is marginal rather than broken. Doubled to stop
  // trimming it by 50% every time the runners get busier; if activation
  // ever genuinely hangs, 60s still fails the run.
  timeout: 60000,
};

// No PartCAD is installed on a CI runner, so activation reaches the "shall I
// download it?" dialog. Nothing in a headless run can answer a modal dialog,
// and on Windows an unanswered one is enough to keep the window from ever
// closing -- which is what "windows-latest doesn't run the test suite" was.
//
// It is set for the bundled run too, where the IDE *does* carry a service: the
// question there is whether the editor comes up and activates the extension,
// and a prompt is still something nothing can answer.
const env = { PARTCAD_EXTENSION_NO_PROMPTS: '1' };

module.exports = defineConfig([
  {
    label: 'unitTests',
    files: 'out/test/**/*.test.js',
    launchArgs: ['--disable-gpu'],
    // version: 'insiders', // For some reason this doesn't work
    workspaceFolder: './sampleWorkspace',
    env,
    mocha,
  },
  // The same suite, in the editor that ships. Skipped when there is no build to
  // point at, so `npm test` is unchanged for anyone without one.
  ...(bundledIde
    ? [
        {
          label: 'bundledIde',
          files: 'out/test/**/*.test.js',
          launchArgs: ['--disable-gpu'],
          workspaceFolder: './sampleWorkspace',
          // Runs this checkout's extension inside the installed application
          // rather than downloading an editor. The built IDE already carries a
          // released copy of this extension; `--extensionDevelopmentPath`,
          // which the runner passes, is what takes precedence over it.
          useInstallation: { fromPath: bundledIde },
          env,
          mocha,
        },
      ]
    : []),
]);
