//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Comparing one file path against another.
//

import * as path from 'path';

/**
 * A key two spellings of the same file share.
 *
 * The extension holds paths from two sources and has to match them up: what
 * VS Code says a document is (`Uri.fsPath`) and what PartCAD says an object is
 * defined by (`item_path`, straight out of Python). On POSIX those are the same
 * string and a `Set` of them works. On Windows they are routinely not:
 * `Uri.fsPath` lower-cases the drive letter, so a document is `c:\...` while
 * everything the daemon reports keeps whatever case the configuration and the
 * working directory had, usually `C:\...`. The filesystem there does not
 * distinguish them and neither may this; a plain string comparison did, which
 * is why `PartcadLint` could never tell a scene from an assembly on Windows and
 * checked every scene against the assembly schema.
 *
 * Case is folded on Windows only. macOS is case-insensitive by default too, but
 * both sides spell a path there the same way, so folding would buy nothing and
 * would be wrong on the case-sensitive volumes that platform also has.
 *
 * The daemon answers the same question with `os.path.samefile`, which is why
 * looking a file up over the wire has always worked. This cannot: it compares
 * paths that need not exist yet -- a buffer being typed into -- so it
 * normalises instead of asking the filesystem.
 *
 * `platform` is a parameter so the test suite can check the platform it is not
 * running on; callers pass nothing.
 */
export function pathKey(value: string, platform: NodeJS.Platform = process.platform): string {
    // The named flavour rather than `path`: they are the same object in
    // production -- `path` is `path.win32` on Windows and `path.posix`
    // everywhere else -- and a test passing `win32` on a Linux runner means a
    // Windows path, which the POSIX rules would take for a relative one and
    // resolve against the runner's working directory.
    const rules = platform === 'win32' ? path.win32 : path.posix;
    const resolved = rules.resolve(value);
    return platform === 'win32' ? resolved.toLowerCase() : resolved;
}
