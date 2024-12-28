# Roadmap

- [MoSCoW method](https://en.wikipedia.org/wiki/MoSCoW_method)

## Must-have / Core

Non-negotiable needs for the project. Product won’t work without an initiative, or the release becomes useless without
it. These are the elements that deliver the primary value to users, solving their most significant problems or
fulfilling the main purpose of the product.

> Tasks are critical to the current delivery [timebox] in order for it to be a success. If even one requirement is not
> included, the project delivery should be considered a failure (note: requirements can be downgraded from Must have, by
> agreement with all relevant stakeholders; for example, when new requirements are deemed more important). MUST can also
> be considered an acronym for the Minimum Usable Subset.

- [ ] Run missing renders automatically for `pc render -t readme`
- [ ] Add search/filter to "Explore" panel.
- [ ] Add "Steps" in AI modifications, similar how Photoshop deals with history of changes.
- [ ] Do not spam to all terminals with `partcad` "build" output.
  - [ ] "$PART_NAME: Showing the part"
- [ ] Handle Ctrl-C gracefully during build.
- [ ] Walk through [Tutorial] in clean VM.
  - There was missing `sudo apt-get install openscad`.
  - Create Behave test for Tutorial?
- [ ] Add Quick Start section on https://partcad.org/
- [ ] Add FAQ section in `./docs` and explain how to:
  - Default windows Python can't compile some of the PartCAD dependencies.
  - Why Part cat contaminates my host env? - Conda for sandboxing, on mac - mamba.
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

## Should have / Quality of Life

Should-have initiatives are just a step below must-haves. They are essential to the product, but they are not vital. If
left out, the product or project still functions. However, the initiatives may add significant value.

“Should-have” initiatives are different from “must-have” initiatives in that they can get scheduled for a future release
without impacting the current one. For example, performance improvements, minor bug fixes, or new functionality may be
“should-have” initiatives. Without them, the product still works.

These are improvements that don’t necessarily add new functionality but refine existing workflows, reduce friction, and
increase efficiency for users.

> Requirements are important but not necessary for delivery in the current delivery [timebox]. While Should have
> requirements can be as important as Must have, they are often not as time-critical or there may be another way to
> satisfy the requirement so that it can be held back until a future delivery [timebox].

- [ ] Allow creating package/directory in PartCAD Explorer.
- [ ] Allow to abort AI generation process.
- [ ] PartCAD Panel shows empty UI during AI generation.
- [ ] Allow removing parts in PartCAD Explorer
- [ ] `ERROR: Can't add files outside of the package`
  - [ ] Do not allow to set path in Command Pallette to "outside of the package"
- [ ] INFO: Script candidate 0: failed to render the image
  - [ ] Convert to warning
- [ ] Automate `git lfs install`.
- [ ] Move allure and poetry plugins to Dockerfile.
- [x] Check how to have this added to Image in different workflow so we compile Python only once.
      [`#discussion_r1860174599`](https://github.com/partcad/partcad/pull/213#discussion_r1860174599)
  - [ ] Release "base" Dev Container image from `main` or `devel` branches.
- [ ] Describe package release flow using [Gitgraph Diagrams](https://mermaid.js.org/syntax/gitgraph.html)
      [`1311532481266188319`](https://discord.com/channels/1308854595987968051/1308857684547600384/1311532481266188319)
- [x] Add `hadolint` in pre-commit hooks.
      [`#discussion_r1860234701`](https://github.com/partcad/partcad/pull/213#discussion_r1860234701)
- [x] Replace with apt-compile.sh
      [`#discussion_r1860160455`](https://github.com/partcad/partcad/pull/213#discussion_r1860160455)
- [x] Move build commands to dedicated shell file.
      [`#discussion_r1858401259`](https://github.com/partcad/partcad/pull/213#discussion_r1858401259)
- [x] IDE settings should go to .vscode/ so they could be changed w/o rebuilding an image.
      [`#discussion_r1858382800`](https://github.com/partcad/partcad/pull/213#discussion_r1858382800)
- [x] `$PATH` problems should be solved.
      [`#discussion_r1858376864`](https://github.com/partcad/partcad/pull/213#discussion_r1858376864)

## Could have / Bells & Whistles

Another way of describing “could-have” initiatives is nice-to-haves. “Could-have” initiatives are not necessary to the
core function of the product. However, compared with “should-have” initiatives, they have a much smaller impact on the
outcome if left out.

So, initiatives placed in the “could-have” category are often the first to be deprioritized if a project in the
“should-have” or “must-have” category ends up larger than expected.

Nice-to-have features that add a layer of delight or polish to the software. These are not essential for core
functionality but can significantly enhance the user experience or make the product stand out.

> Requirements labelled as Could have are desirable but not necessary and could improve the user experience or customer
> satisfaction for a little development cost. These will typically be included if time and resources permit.

- - [Improve logging in Poetry glibc version check](https://github.com/python-poetry/poetry/issues/9837)
- [ ] All DeepSpaceCartel code should be transferred to PartCAD.
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
- [x] Run `pre-commit` workflow in Dev Container.

## Won't have (this time)

> Requirements labelled as Won't have, have been agreed by stakeholders as the least-critical, lowest-payback items, or
> not appropriate at that time. As a result, Won't have requirements are not planned into the schedule for the next
> delivery timebox. Won't have requirements are either dropped or reconsidered for inclusion in a later timebox.

[Tutorial]: https://partcad.readthedocs.io/en/latest/tutorial.html
[timebox]: https://en.wikipedia.org/wiki/Timeboxing
