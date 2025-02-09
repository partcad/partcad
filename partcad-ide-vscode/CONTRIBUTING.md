
# PartCAD Visual Studio Code Extension

## Submitting your changes

Please, create a pull requestion.

## Building and packaging

1. Run `nox --session setup` once?
1. Build package using `nox --session build_package`.

## Upgrading dependencies

Dependabot yml is provided to make it easy to setup upgrading dependencies in this extension. Be sure to add the labels used in the dependabot to your repo.

To manually upgrade your local project:

1. Create a new branch
1. Run `npm update` to update node modules.
1. Run `nox --session setup` to upgrade python packages.
