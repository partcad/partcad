---
name: search
description: Find existing PartCAD parts and assemblies in the catalog that match a natural-language query, using the PartCAD CLI (`pc search`), then present the matches and optionally inspect or render a chosen one. Use for /pc:search or when the user asks to search, find, look up, or discover a part or assembly.
---

# pc:search

Find existing PartCAD **parts and assemblies** that match a query, using
PartCAD's own `pc search`. The text after the command (`$ARGUMENTS`) is what to
look for — a natural-language description or a set of keywords. Present the
matches and, when the user points at one, act on it (inspect or render). This
searches the existing catalog; it does **not** create anything — to generate a
new object, use `/pc:gen` instead.

## 1. Understand the request

- `$ARGUMENTS` is the query. `pc search` matches a **single keyword** as a
  case-insensitive substring against each object's name, its configured fields
  (`desc`, `type`, `path`, …), and the contents of its source file. It does not
  parse natural language and does not rank by relevance.
- So distill the query into a few concrete terms — e.g. "M3 hex standoff" →
  `standoff`, `hex`, `m3` — search each, then union the results yourself.
- Decide the scope. The default is the local/root package (`//`); the public
  PartCAD registry and other imported packages are only reached with `-r`.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:install executable` first.

## 3. Search

Run one search per object kind you care about — parts and assemblies — for each
keyword. The keyword is the **required** `-k`/`--keyword` option (quote
multi-word terms):

```sh
pc search parts -k "<keyword>"          # search parts
pc search assemblies -k "<keyword>"     # search assemblies
```

Widen the scope when the local package has no match — `-r` walks every imported
package (the public registry and any dependencies), which is where most catalog
items live. Use `-P` to scope to one package subtree:

```sh
pc search parts -k "<keyword>" -r                 # all imported packages
pc search parts -k "<keyword>" -P //pub/std -r    # scope to one package subtree
```

Sibling commands share the same flags if the query is broader: `pc search all`
(parts, sketches, interfaces, assemblies, and packages at once), plus
`pc search sketches`, `pc search interfaces`, and `pc search packages`.

Each match prints as `<package> <name>` followed by its description, and the run
ends with `Matches: N` (or `<none>`). Read both columns — the package tells you
where the object lives, which you need in order to act on it.

## 4. Present the results

Collect the matches across all the keywords you tried, drop duplicates, and show
the user a short list: the qualified name (`<package> <name>`) and its
description, best-fit first (you judge fit from the description — the tool does
not order results). If nothing matched, say so and suggest widening with `-r`,
trying different terms, or generating it with `/pc:gen`.

## 5. Act on a chosen result (optional)

When the user picks a match, reference it by the two columns the search printed —
`-P <package>` plus the object name; add `-a` when it is an assembly:

```sh
pc inspect -P <package> <name>                            # view a part; add -a for an assembly
mkdir -p /tmp/pc-render                                    # the -O directory must already exist
pc render -t png -O /tmp/pc-render -P <package> <name>     # writes a PNG under /tmp/pc-render; add -a for an assembly
```

Then follow up as the user asks — for example describe it with `/pc:describe`,
or add it to their project.
