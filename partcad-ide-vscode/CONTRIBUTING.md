# PartCAD Visual Studio Code Extension

## Submitting your changes

Please create a pull request.

## Building and packaging

1. Run `nox --session setup` to initialize the development environment and install dependencies.
2. Build package using `nox --session build_package` to create the VS Code extension package.

## Upgrading dependencies

Dependabot yml is provided to make it easy to setup upgrading dependencies in this extension. Be sure to add the labels used in the dependabot to your repo.

To manually upgrade your local project:

1. Create a new branch for dependency updates
2. Run `npm update` to update Node.js dependencies to their latest compatible versions
3. Run `nox --session setup` to upgrade Python packages to their latest compatible versions
4. Test the extension thoroughly after upgrading dependencies
