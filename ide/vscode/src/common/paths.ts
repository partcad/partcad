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

/**
 * A path PartCAD reports, spelled for someone looking at this workspace.
 *
 * Relative to the workspace folder holding it, and led by `.` so that it reads
 * as a path -- `./partcad.yaml`, `./sub/partcad.yaml` -- or as it was given
 * when no folder holds it. The service reports absolute paths, and relative to
 * what is a question only this side can answer: the daemon's own working
 * directory is `/` on POSIX, and making the path relative to *that* is what
 * once showed `/home/me/pkg/partcad.yaml` as `.home.me.pkg.partcad.yaml`.
 *
 * A value that is not absolute is returned untouched. It is not a path this
 * can place: the view's placeholder, or what an older service sent having
 * already made it relative to a directory this side cannot know.
 *
 * `platform` is a parameter for the reason it is one in `pathKey`; callers
 * pass nothing. Windows compares the folder case-insensitively, as `pathKey`
 * does, because `path.win32.relative` does.
 */
export function workspacePath(
    value: string,
    folders: readonly string[],
    platform: NodeJS.Platform = process.platform,
): string {
    const rules = platform === 'win32' ? path.win32 : path.posix;
    if (!rules.isAbsolute(value)) {
        return value;
    }
    for (const folder of folders) {
        const relative = rules.relative(folder, value);
        // Another drive comes back absolute, and outside the folder starts by
        // climbing out of it.
        if (relative !== '' && !rules.isAbsolute(relative) && relative.split(rules.sep)[0] !== '..') {
            return `.${rules.sep}${relative}`;
        }
    }
    return value;
}
