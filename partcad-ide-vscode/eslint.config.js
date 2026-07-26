// ESLint flat configuration (ESLint 9+).
//
// Ported from the legacy .eslintrc.json. The rule set is intentionally kept
// identical to the previous configuration; the migration only changes the file
// format (flat config) that ESLint 9 requires. The TypeScript parser and plugin
// are wired in explicitly rather than through a shared preset so that the exact
// same rules keep applying.
const tsParser = require('@typescript-eslint/parser');
const tsPlugin = require('@typescript-eslint/eslint-plugin');

module.exports = [
    {
        // Replaces the legacy "ignorePatterns" field.
        ignores: ['node_modules/**', 'out/**', 'dist/**', '**/*.d.ts'],
    },
    {
        files: ['src/**/*.ts'],
        languageOptions: {
            parser: tsParser,
            ecmaVersion: 2022,
            sourceType: 'module',
        },
        plugins: {
            '@typescript-eslint': tsPlugin,
        },
        rules: {
            '@typescript-eslint/naming-convention': 'warn',
            curly: 'warn',
            eqeqeq: 'warn',
            'no-throw-literal': 'warn',
            semi: 'off',
        },
    },
];
