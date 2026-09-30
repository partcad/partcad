//@ts-check

const path = require('path');

//@ts-check
/** @typedef {import('webpack').Configuration} WebpackConfig **/

/** @type WebpackConfig */
const extensionConfig = {
  target: 'node', // vscode extensions run in a Node.js-context 📖 -> https://webpack.js.org/configuration/node/
  mode: 'none', // this leaves the source code as close as possible to the original (when packaging we set this to 'production')

  entry: './src/extension.ts', // the entry point of this extension, 📖 -> https://webpack.js.org/configuration/entry-context/
  output: {
    // the bundle is stored in the 'dist' folder (check package.json), 📖 -> https://webpack.js.org/configuration/output/
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs2',
  },
  externals: {
    vscode: 'commonjs vscode', // the vscode-module is created on-the-fly and must be excluded. Add other modules that cannot be webpack'ed, 📖 -> https://webpack.js.org/configuration/externals/
    // modules added here also need to be added in the .vscodeignore file
  },
  resolve: {
    // support reading TypeScript and JavaScript files, 📖 -> https://github.com/TypeStrong/ts-loader
    extensions: ['.ts', '.js'],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader',
          },
        ],
      },
      {
        test: /\.css$/,
        use: [
          'style-loader',
          'css-loader'
        ]
      }
    ],
  },
  devtool: 'source-map',
  infrastructureLogging: {
    level: 'log', // enables logging required for problem matchers
  },
};

/**
 * The PartCAD Viewer's renderer, bundled separately from the extension.
 *
 * It runs inside a webview, which is a browser context: it must not be built for
 * 'node' (no require, no Buffer) and it must be fully self-contained, because
 * the panel's CSP forbids loading anything from a CDN. That is why three.js is
 * bundled in rather than linked.
 *
 * @type WebpackConfig
 */
const viewerConfig = {
  target: 'web',
  mode: 'none',

  entry: './src/webview/viewer.ts',
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'viewer.js',
  },
  resolve: {
    extensions: ['.ts', '.js'],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader',
            options: {
              // three.js ships its addons as ES modules only, which the
              // extension's CommonJS configuration cannot import.
              configFile: 'tsconfig.webview.json',
            },
          },
        ],
      },
    ],
  },
  devtool: 'source-map',
  infrastructureLogging: {
    level: 'log',
  },
};

module.exports = [extensionConfig, viewerConfig];
