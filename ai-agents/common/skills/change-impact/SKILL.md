---
name: change-impact
description: Work out what a design change does to everything downstream of it - what changed in each object of a PartCAD package since a revision (a tag, a commit or a branch), how the mass, volume and shape of each changed part moved, which assemblies use it and how many times, how each affected assembly's bill of materials changed, whether it all still passes qualification, and which drawings, files, instructions and suppliers that touches - written up as a draft engineering change notice, a BOM delta CSV and a manifest. Use for /pc:change-impact, or when the user asks what a change affects, for an ECN, ECO or ECR, a where-used or impact analysis, what to tell suppliers, or what changed since the last release or the last RFQ - including when a quality or supply-chain skill of another plugin, such as Claude for Manufacturing, needs the engineering side of a change. It leaves the disposition and the effectivity to a person.
---

# pc:change-impact

Say what a design change reaches before anybody acts on it. `$ARGUMENTS` names
the revision to compare against and, optionally, the objects to start from
(otherwise everything that changed in the package), and where to write.

A change notice is read by people who did not make the change — purchasing,
quality, the shop floor, a supplier — and each of them asks one question: *does
this affect me?* So it has to name every affected thing, not just the part that
was edited, and every claim in it has to come from a command that can be run
again. What it must not do is decide: whether parts already made are used as
they are, reworked or scrapped (the **disposition**), and from which unit or
date the change applies (the **effectivity**), are decisions for a person, and
the notice leaves them blank.

## 1. Settle what is compared

- **The revision** — what the change is measured from: a tag (`v1.2`,
  `rfq/bracket/2026-11-02` if `/pc:rfq-pack` was sent from one), a commit, or a
  branch. If it was not said, list the candidates and ask:

  ```sh
  git -C <package dir> tag --sort=-creatordate | head
  pc --no-ansi revisions list 2>&1           # the commits that changed this package, newest first
  ```

- **The current side** — the package as it is on disk. A revision is read from
  git; the current side includes uncommitted edits, so record whether there are
  any (`git status --porcelain -- .`) and say so in the notice.
- **The destination** — as `/pc:rfq-pack` §1, defaulting to
  `./out/change/<package>-<revision>-<YYYY-MM-DD>/`.

Resolve `pc`, pass `--no-ansi` and capture both streams as `/pc:rfq-pack` §2
says; without a shell, the `partcad` MCP server's `diff`, `revisions`,
`used_by`, `compare`, `bom` and `qual_test` tools do what the commands below do.

A package at a revision is named `<package>@<revision>`, everywhere an object
is named: `//shop/brackets@v1.2:corner` is the corner bracket as tagged
`v1.2`. The full package name is the `Path` that `pc --no-ansi info <object>`
reports. PartCAD writes the revision out of git into `~/.partcad/git` and never
into it, so nothing here can change the revision being compared against.

## 2. What changed

```sh
pc --no-ansi revisions diff <revision> 2>&1             # the package's partcad.yaml, rendered, then and now
pc --no-ansi revisions diff <revision> <object> 2>&1    # one object, then and now
git -C <package dir> log --format='%h %ad %an %s' --date=short <revision>..HEAD -- .
git -C <package dir> diff --stat <revision> -- .
```

`pc revisions diff` compares what each object *means* — its declaration,
rendered, with defaults left out — so a reworded comment is no change. Prints
nothing when nothing changed; `--json` adds the rows side by side.

It compares declarations, and an object is also its **files**: a script, a
STEP file, a sketch it is extruded from. So read `git diff --stat` too, and treat
every object built from a file that changed as changed — `pc --no-ansi info
<object>` names its file. The commit messages are what the notice gives as the
reason for the change; quote them, do not paraphrase them into a reason they do
not give.

A change can also arrive from a **dependency**: `pc update` moves the
`revision:` a dependency is pinned to, and every part used from it may have
changed with no file of this package touched. The package diff shows the
`revision:` lines that moved; `pc --no-ansi revisions uses <revision>` lists the
dependencies as they were pinned then. Compare each part this package uses from
a moved dependency as in §3, naming it at both pins
(`<dependency>@<old commit>:<part>` against `<dependency>:<part>`).

Make the list of **changed objects**: added, removed, and modified, each with
what changed in a line.

## 3. How each changed part moved

For each part (or assembly) that exists on both sides:

```sh
pc --no-ansi compare --json <package>@<revision>:<object> <object> 2>/dev/null
pc --no-ansi compare --json --surface-distance 1 <package>@<revision>:<object> <object> 2>/dev/null
```

The first gives the volume and the mass of each and the difference, and the
tolerance each is made to; the second also measures how far the new surface
stands from the old one along the old one's normals, with how many points are
further apart than the two tolerances allow. Report the numbers as they come
back. A difference within the allowance on every point is still a change, but
it is the evidence for a disposition of *use as is*; say so, and leave the
deciding to the reader. Use `--surface-distance` on parts, where it is cheap; on
a large assembly it is slow, and the parts' own comparisons say the same.

A picture is the quickest thing for a reader to check. Render both sides into
directories of their own, since both files are named after the object:

```sh
mkdir -p <destination>/views/before <destination>/views/after
pc --no-ansi render -t png --view iso -O <destination>/views/before <package>@<revision>:<object> 2>&1
pc --no-ansi render -t png --view iso -O <destination>/views/after <object> 2>&1
```

## 4. Where it is used

```sh
pc --no-ansi used-by --load --json <object> 2>/dev/null
```

lists every object PartCAD can load from this workspace that places it, and how
many times. Follow it upward — ask again for each assembly it names — until
nothing uses the assembly: those are the **top-level** objects, the products.

Two kinds of use it does not see, and you have to:

- **Made from.** A part cut from a changed piece of stock does not *place* it;
  it names it as its `manufacturing:` `source:`. Look in every `partcad.yaml`
  of the workspace for `source:` naming a changed object, and treat each part
  that does as changed too.
- **Other repositories.** Only what can be loaded from here is asked. Packages
  elsewhere that depend on this one are not, and the notice says so.

## 5. What it does to each bill of materials

For each top-level object, and each affected assembly someone orders from:

```sh
pc --no-ansi bom -j <package>@<revision>:<assembly> 2>/dev/null > before.json
pc --no-ansi bom -j <assembly> 2>/dev/null > after.json
```

Compare them line by line, by `name`. An item of the same package is named
`<package>@<full commit id>:<item>` on the revision's side and `<package>:<item>`
on the current one: drop the `@<commit id>` before matching. Each line is
**added**, **removed**, **quantity changed** (`count`), **source changed**
(`vendor`, `sku` or `count_per_sku`) or unchanged; only the first four go into
`bom-delta.csv`. An assembly that is new has no *before*, and one that was
removed no *after*.

## 6. Does it still pass

```sh
pc --no-ansi qual test <object> 2>&1                # each changed object
pc --no-ansi qual test <assembly> 2>&1              # each affected assembly
pc --no-ansi req list --json --verify <object> 2>/dev/null   # its requirements, with a verdict for each
```

A check that passes prints nothing; a finding is a warning or an error naming
the check, and an error is a failure. A requirement whose features are prose is
judged by `/pc:validate`, not here: say which those are, and suggest running it.
Report failures verbatim. A change that fails qualification is not one to
release, and the notice says that first.

## 7. What has to be reissued, and who is told

From everything above, list:

- **Files**: each changed part's STEP, mesh and drawing; each affected
  assembly's STEP and assembly instructions. Where a `/pc:rfq-pack` or
  `/pc:quote-pack` was produced from the revision, it is out of date — name it.
- **Suppliers**: the `vendor` of each bought line that was added, removed or
  changed; and for each changed part made by a supplier, that supplier, which
  PartCAD does not know — leave it for the user to fill in rather than guessing.
- **People**: whoever builds each affected assembly (the instructions changed)
  and whoever inspects each changed part (what it is measured against changed).

## 8. Write the files

```
<destination>/
  ecn.md            the draft change notice
  bom-delta.csv     one row per changed line of each bill of materials
  manifest.json     where every figure came from
  views/            before/ and after/ pictures of each changed object
```

### `bom-delta.csv`

```
assembly,item,change,count_before,count_after,vendor_before,vendor_after,sku_before,sku_after,count_per_sku_before,count_per_sku_after,description
```

`change` is `added`, `removed`, `quantity`, or `source`.

### `ecn.md`

In this order, as headings:

1. **Change** — the number left blank for the user's own system, a title, the
   package, the revision compared against and the commit compared (and whether
   uncommitted edits are included), the date.
2. **Reason** — the commit messages, quoted.
3. **Qualification** — pass or fail first, then each failure verbatim.
4. **Changed objects** — each with what changed, and for parts the mass,
   volume and surface-distance figures, before → after.
5. **Affected** — every assembly and product that uses a changed object, with
   how many it uses, and the parts made from changed stock.
6. **Bill of materials** — the delta, per assembly, in words and as a table.
7. **To reissue** and **to notify** — §7.
8. **Not checked** — packages outside this workspace, requirements left to
   `/pc:validate`, anything a command could not answer.
9. **Disposition** and **effectivity** — blank, for a person: *use as is*,
   *rework* or *scrap* for each part already made or on order, and the unit,
   lot or date the change applies from.

### `manifest.json`

The same shape as `/pc:rfq-pack`'s, with `"kind": "change-impact"`, the
revision compared against (as given and as the full commit id), the commit
compared, and every command whose output a figure in `ecn.md` came from.

## 9. Report

Lead with whether the change passes qualification, then how many objects
changed and how many assemblies and products that reaches, the bill-of-materials
lines that changed, and what is left for a person to decide. Name the files.
