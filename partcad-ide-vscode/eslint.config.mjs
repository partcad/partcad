import typescriptEslint from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';

export default [
  {
    ignores: ["**/out", "**/dist", "**/*.d.ts"],
  },
  {
    files: ["**/*.ts", "**/*.tsx"],
    plugins: {
      "@typescript-eslint": typescriptEslint,
    },
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 6,
        sourceType: "module",
        project: './tsconfig.json', // Adjust this path if needed
      },
    },
    rules: {
      "@typescript-eslint/naming-convention": "warn",
      curly: "warn",
      eqeqeq: "warn",
      "no-throw-literal": "warn",
      semi: "off",
      // Additional TypeScript-specific rules (optional)
      // "@typescript-eslint/explicit-function-return-type": "warn",
      // "@typescript-eslint/no-explicit-any": "warn",
      // "@typescript-eslint/no-unused-vars": "warn",
    },
  },
];
