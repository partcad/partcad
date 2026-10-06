//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The garage: what this user decided about the objects they build, kept on this
// machine.
//
// So far that is one decision - which lines of an object's Build vs Buy table
// are built and which are bought - in one file per object:
//
//     ~/.partcad/garage/default/bvb/<escaped object name>.json
//     {"object": "//package:name", "choices": {"//package:part": "build", ...}}
//
// On the client, and never on the daemon. It is a decision about how *this*
// person gets hold of the thing - whether they own a CNC router, whether they
// would rather pay someone - and the daemon may be shared, or somebody else's
// machine altogether. The CLI reads the same files (`partcad_utils.garage`) when
// it asks for assembly instructions, which is why the layout is fixed rather
// than private to the extension: the escaping below has to produce the file name
// Python's `urllib.parse.quote(name, safe="")` does, byte for byte.
//
// `default` is the garage: one, for now, and named so that a second - a work
// shop beside a home one - is a directory rather than a migration.
//

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

export type Choices = Record<string, 'build' | 'buy'>;

/**
 * Where PartCAD keeps its per-user state: `~/.partcad`.
 *
 * `$HOME` first, as `UserConfig.get_config_dir()` reads it, so that the CLI and
 * the extension agree on a machine where the two differ (a `HOME` pointed
 * somewhere on purpose, which is what every PartCAD test does).
 */
export function partcadHome(home: string = process.env.HOME || os.homedir()): string {
    return path.join(home, '.partcad');
}

/** The directory the Build vs Buy choices are kept in. */
export function bvbDirectory(home?: string): string {
    return path.join(partcadHome(home), 'garage', 'default', 'bvb');
}

/**
 * An object's name as a file name: every byte of its UTF-8 outside
 * `[A-Za-z0-9_.~-]` as `%XX`.
 *
 * `encodeURIComponent` leaves five more characters alone than Python's `quote`
 * does, and `*` among them is not allowed in a Windows file name, so those five
 * are encoded too.
 */
export function escapeName(name: string): string {
    return encodeURIComponent(name).replace(
        /[!'()*]/g,
        (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
    );
}

/** The file one object's choices are kept in. */
export function bvbPath(object: string, home?: string): string {
    return path.join(bvbDirectory(home), `${escapeName(object)}.json`);
}

/**
 * The choices last saved for an object, or none.
 *
 * A missing file is the ordinary case - nobody has moved a switch yet - and a
 * file that cannot be read or parsed is treated the same way: the defaults are a
 * table the user can work from, and an error over a preference is not.
 */
export function readChoices(object: string, home?: string): Choices {
    try {
        const parsed = JSON.parse(fs.readFileSync(bvbPath(object, home), 'utf8')) as unknown;
        const choices = (parsed as { choices?: unknown })?.choices;
        if (choices === null || typeof choices !== 'object' || Array.isArray(choices)) {
            return {};
        }
        const result: Choices = {};
        for (const [name, value] of Object.entries(choices as Record<string, unknown>)) {
            if (value === 'build' || value === 'buy') {
                result[name] = value;
            }
        }
        return result;
    } catch {
        return {};
    }
}

/**
 * Keep an object's choices, replacing what was kept.
 *
 * Written beside the target and renamed over it, so that a reader - the CLI,
 * another window - never sees half a file.
 */
export function writeChoices(object: string, choices: Choices, home?: string): void {
    const file = bvbPath(object, home);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temporary = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify({ object, choices }, null, 2) + '\n', 'utf8');
    fs.renameSync(temporary, file);
}
