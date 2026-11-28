//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the host does for the Digital Thread's Operations tabs: which command
// each of the daemon's 'ops.*' methods is asked through, what it is asked
// about, who the author of a new revision is, and why the daemon would not
// make one.
//
// The subject is the object on screen, or its package - or the package at a
// state, '<package>@<sha>' or '<package>@STAGED', which is how the daemon is
// asked about a package at a revision. The renderer says which ('at', 'whole');
// the names are put together here, in one place.
//
// The author is git's on this machine ('git config user.name' and 'user.email'
// in the package's repository, where a repository's own identity applies), read
// here and sent with the request, and never the daemon's: a daemon can be on
// somebody else's machine, whose git configuration names whoever runs it there.
// The Python twin, for 'pc ops rev new', is 'partcad_utils.git_identity'.
//
// Free of 'vscode', so that it can be tested outside an editor.
//

import * as fs from 'fs';
import { gitConfig } from './comments';

/**
 * The command each Operations method is asked through ('src/common/backend.ts'),
 * and whether it changes anything: a change is never cancelled, and is asked
 * with 'opsWrite' rather than 'fetchTab'.
 */
export const OPS_COMMANDS: Record<string, { command: string; writes: boolean }> = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.rev.list': { command: 'partcad.opsRevList', writes: false },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.rev.diff': { command: 'partcad.opsRevDiff', writes: false },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.rev.status': { command: 'partcad.opsRevStatus', writes: false },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.rev.stage': { command: 'partcad.opsRevStage', writes: true },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.rev.new': { command: 'partcad.opsRevNew', writes: true },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.deps.list': { command: 'partcad.opsDepsList', writes: false },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.deps.add': { command: 'partcad.opsDepsAdd', writes: true },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.deps.remove': { command: 'partcad.opsDepsRemove', writes: true },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.deps.update': { command: 'partcad.opsDepsUpdate', writes: true },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.used_by': { command: 'partcad.opsUsedBy', writes: false },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'ops.impact': { command: 'partcad.opsImpact', writes: false },
};

/** The Operations tabs, and the question each asks first when it names none. */
export const OPS_TABS: Record<string, string> = {
    revisions: 'ops.rev.list',
    dependencies: 'ops.deps.list',
    usedby: 'ops.used_by',
    impact: 'ops.impact',
};

/** One question or change as the renderer sends it; see 'OpsQuery' in 'webview/messages.ts'. */
export interface OpsRequest {
    method: string;
    at?: string;
    whole?: boolean;
    params?: Record<string, unknown>;
}

/** What the object on screen is, as the show said it. */
export interface OpsTarget {
    package?: string | null;
    name?: string | null;
    kind?: string | null;
}

/**
 * The arguments of an Operations command: the subject - the object on screen,
 * or its package, or the package at a state - and what the renderer asked it
 * with. A package names no object, which is how the daemon tells the two apart.
 * A dependency's name travels as 'dependency', since 'name' is the subject's.
 */
export function opsArgs(target: OpsTarget, request: OpsRequest): Record<string, unknown> {
    const whole = request.whole === true || target.kind === 'package';
    const { name: dependency, ...params } = request.params ?? {};
    return {
        ...params,
        dependency,
        pkg: request.at ? `${target.package}@${request.at}` : target.package,
        name: target.name,
        kind: whole ? 'package' : (target.kind ?? undefined),
    };
}

/** What to say when git does not say who the author is, which is a revision nobody can make. */
export const NO_IDENTITY =
    'Nobody to make the revision as: set your name and email with git config --global user.name "Your Name" ' +
    'and git config --global user.email "you@example.com", and make it again.';

/**
 * Who is making a revision: 'git config user.name' and 'user.email', asked in
 * 'directory' - the package's repository - or, where that is not on this
 * machine (the daemon is somebody else's), in 'fallback', the workspace. A
 * value git does not know is left out.
 */
export async function gitIdentity(
    directory: string | null | undefined,
    fallback?: string,
    git = 'git',
): Promise<{ name?: string; email?: string }> {
    const cwd = directory && fs.existsSync(directory) ? directory : fallback;
    const [name, email] = await Promise.all([gitConfig('user.name', cwd, git), gitConfig('user.email', cwd, git)]);
    return { ...(name ? { name } : {}), ...(email ? { email } : {}) };
}

/**
 * Why the daemon would not make a revision, when that is what an error is: its
 * 'data' ({'code', 'status'}), so that the tab can ask the user to agree and
 * send it again. Undefined for any other error.
 */
export function refusalOf(error: unknown): { code: string; status?: unknown } | undefined {
    const data = (error as { data?: unknown } | null | undefined)?.data;
    if (typeof data !== 'object' || data === null) {
        return undefined;
    }
    const code = (data as { code?: unknown }).code;
    if (typeof code !== 'string') {
        return undefined;
    }
    return { code, status: (data as { status?: unknown }).status };
}

/** What a change is doing, in a few words, for the notification that says it is under way. */
export function opsDoing(method: string, name: string | null | undefined): string {
    const what = name ?? 'this';
    switch (method) {
        case 'ops.rev.stage':
            return `staging the changes of ${what}`;
        case 'ops.rev.new':
            return `making a revision of ${what}`;
        case 'ops.deps.add':
            return 'declaring a dependency';
        case 'ops.deps.remove':
            return 'removing a dependency';
        case 'ops.deps.update':
            return 'updating the dependencies';
        default:
            return 'changing it';
    }
}
