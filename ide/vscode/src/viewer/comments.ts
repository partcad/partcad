//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the host does for the 3D view's comments that only this machine can:
// say who is writing one, and turn the files somebody picked to attach into
// the names a comment keeps.
//
// The name is git's on this machine ('git config user.name'), read here and
// sent with the comment, and never the daemon's: a daemon can be on somebody
// else's machine, whose git configuration names whoever runs it there. The
// Python twin, for 'pc comment add', is 'partcad_utils.comments.author'.
//
// Free of 'vscode', so that it can be tested outside an editor.
//

import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

/** What to say when git names nobody, which is a comment nobody can sign. */
export const NO_AUTHOR =
    'Nobody to sign the comment with: set your name with git config --global user.name "Your Name" and post it again.';

/**
 * Who is writing a comment: 'git config user.name', asked in 'cwd' - the
 * workspace, where a repository's own identity applies - or undefined where
 * git names nobody, or is not there to ask.
 */
export function gitAuthor(cwd?: string, git = 'git'): Promise<string | undefined> {
    const directory = cwd !== undefined && fs.existsSync(cwd) ? cwd : undefined;
    return new Promise((resolve) => {
        execFile(git, ['config', 'user.name'], { cwd: directory, timeout: 10_000 }, (error, stdout) => {
            const name = error ? '' : String(stdout).trim();
            resolve(name || undefined);
        });
    });
}

/**
 * The files picked to attach, as a comment keeps them: relative to the package
 * 'directory', '/'-separated. A file outside the package is not one a comment
 * can name - it is read wherever the package is - and is returned in 'outside'.
 */
export function attachmentNames(directory: string, files: readonly string[]): { files: string[]; outside: string[] } {
    const named: string[] = [];
    const outside: string[] = [];
    const root = path.resolve(directory);
    for (const file of files) {
        const relative = path.relative(root, path.resolve(file));
        if (relative === '' || relative.startsWith('..') || path.isAbsolute(relative)) {
            outside.push(file);
        } else {
            named.push(relative.split(path.sep).join('/'));
        }
    }
    return { files: named, outside };
}
