# Roadmap

## In Progress

These items are actively being worked on by the team, whether they involve coding, design, testing, or review. Progress
is being tracked to ensure timely completion, and these items are not yet ready for release. The focus here is on
solving blockers and refining functionality to align with user needs and project goals.

## Core

These are the elements that deliver the primary value to users, solving their most significant problems or fulfilling
the main purpose of the product.

- [x] Replace `https://github.com/openvmp/...` with `https://github.com/partcad/...`
- [x] Replace 80 to 120 everywhere
      [`#discussion_r1860553570`](https://github.com/partcad/partcad/pull/213#discussion_r1860553570).
- [x] Mention glibc problem in docs
      [`#discussion_r1860158622`](https://github.com/partcad/partcad/pull/213#discussion_r1860158622)
- [x] Add poetry to `dependabot`
      [`#discussion_r1858388007`](https://github.com/partcad/partcad/pull/213#discussion_r1858388007).
- [x] Run `pre-commit` in the "check" mode for PRs
      [`#discussion_r1858385853`](https://github.com/partcad/partcad/pull/213#discussion_r1858385853)
- [x] All those dependencies should be explained in `./docs/` -
      [`#discussion_r1858361949`](https://github.com/partcad/partcad/pull/213#discussion_r1858361949)
- [x] `poetry` should be explained in `./docs`.
      [`#discussion_r1858368911`](https://github.com/partcad/partcad/pull/213#discussion_r1858368911)
- [x] Perhaps we need to drop all personal names everywhere. Leave the company info if there is a field for that
      [`#discussion_r1858409903`](https://github.com/partcad/partcad/pull/213#discussion_r1858409903)
- [x] `pre-commit` should activate itself automatically.
      [`#discussion_r1858368911`](https://github.com/partcad/partcad/pull/213#discussion_r1858368911)
- [x] Mention in docs pre-commit hooks auto-install.
      [`#discussion_r1860175130`](https://github.com/partcad/partcad/pull/213#discussion_r1860175130)

## Quality of Life

These are improvements that don’t necessarily add new functionality but refine existing workflows, reduce friction, and
increase efficiency for users.

- [ ] Check how to have this added to Image in different workflow so we compile Python only once.
      [`#discussion_r1860174599`](https://github.com/partcad/partcad/pull/213#discussion_r1860174599)
  - [ ] Release "base" Dev Container image from `main` or `devel` branches.
- [ ] Describe package release flow using [Gitgraph Diagrams](https://mermaid.js.org/syntax/gitgraph.html)
      [`1311532481266188319`](https://discord.com/channels/1308854595987968051/1308857684547600384/1311532481266188319)
- [x] Add hadolint in pre-commit hooks.
      [`#discussion_r1860234701`](https://github.com/partcad/partcad/pull/213#discussion_r1860234701)
- [x] Replace with apt-compile.sh
      [`#discussion_r1860160455`](https://github.com/partcad/partcad/pull/213#discussion_r1860160455)
- [x] Move build commands to dedicated shell file.
      [`#discussion_r1858401259`](https://github.com/partcad/partcad/pull/213#discussion_r1858401259)
- [x] IDE settings should go to .vscode/ so the could be changed w/o rebuilding an image.
      [`#discussion_r1858382800`](https://github.com/partcad/partcad/pull/213#discussion_r1858382800)
- [x] `$PATH` problems should be solved.
      [`#discussion_r1858376864`](https://github.com/partcad/partcad/pull/213#discussion_r1858376864)

## Bells & Whistles

Nice-to-have features that add a layer of delight or polish to the software. These are not essential for core
functionality but can significantly enhance the user experience or make the product stand out.

- [ ] Run `pre-commit` workflow in Dev Container.
- [ ] All used deepspacecatel code should be transferred to PartCAD.
      [`#discussion_r1858374297`](https://github.com/partcad/partcad/pull/213#discussion_r1858374297)
- [ ] Create separate ticket for poetry-multiproject
      [`#discussion_r1858404314`](https://github.com/partcad/partcad/pull/213#discussion_r1858404314)
- [ ] Sort file. [`#discussion_r1860165309`](https://github.com/partcad/partcad/pull/213#discussion_r1860165309)
- [ ] Add comment what's using it.
      [`#discussion_r1860168439`](https://github.com/partcad/partcad/pull/213#discussion_r1860168439)
- [ ] Add a comment on what's upstream dependency.
      [`#discussion_r1860171323`](https://github.com/partcad/partcad/pull/213#discussion_r1860171323)
- [ ] Fix DeprecationWarning during pytest
      [`#discussion_r1860188980`](https://github.com/partcad/partcad/pull/213#discussion_r1860188980)
- [ ] Automate allowedSignersFile configuration.
      [`#discussion_r1860184779`](https://github.com/partcad/partcad/pull/213#discussion_r1860184779)
      [`#discussion_r1860183016`](https://github.com/partcad/partcad/pull/213#discussion_r1860183016)
- [ ] Add error check to `git config user.email`
      [`#discussion_r1860179677`](https://github.com/partcad/partcad/pull/213#discussion_r1860179677)
