//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Choosing a standalone bundle out of a release manifest. The archives are
// named after the OS version they were frozen on, so which one to download is a
// question about the release *and* about this machine -- and the extension is
// the one consumer of that policy which cannot share the Python implementation.
//

import * as assert from 'assert';

// Architecture names are not camelCase; that is not a code-style choice.
/* eslint-disable @typescript-eslint/naming-convention */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { resolveServicePath, selectPlatforms, serviceUnder } from '../../common/provision';

const MANIFEST = {
    version: '0.7.177',
    bundle: {
        linux: {
            x86_64: ['ubuntu-24.04-x86_64', 'ubuntu-22.04-x86_64'],
            arm64: ['ubuntu-24.04-arm64', 'ubuntu-22.04-arm64'],
        },
        macos: { arm64: ['macos-26-arm64', 'macos-15-arm64'] },
        // One Windows build, not one per image: nothing here can be compared
        // against a Windows host, and there is no floor for two builds to
        // differ in. See the note beside the matrix in "build-standalone.yml".
        windows: { x86_64: ['windows-2022-x86_64'] },
    },
    ide: {
        linux: { x86_64: ['linux-x86_64'] },
        macos: { arm64: ['macos-arm64'] },
        windows: { x86_64: ['windows-x86_64'] },
    },
};

suite('Release manifest', () => {
    test('a matching host gets its own build first', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'linux', 'x86_64', 'ubuntu-24.04'), [
            'ubuntu-24.04-x86_64',
            'ubuntu-22.04-x86_64',
        ]);
    });

    test('a build newer than the host is never offered', () => {
        // 22.04 cannot run a bundle frozen on 24.04: the glibc it needs is not there.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'linux', 'x86_64', 'ubuntu-22.04'), [
            'ubuntu-22.04-x86_64',
        ]);
    });

    test('a host newer than every build gets all of them, newest first', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'macos', 'arm64', 'macos-27'), [
            'macos-26-arm64',
            'macos-15-arm64',
        ]);
    });

    test('a host older than every build still gets the oldest one', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'macos', 'arm64', 'macos-14'), ['macos-15-arm64']);
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'linux', 'x86_64', 'ubuntu-20.04'), [
            'ubuntu-22.04-x86_64',
        ]);
    });

    test('an unidentified host is offered the most portable build first', () => {
        // A Linux that is not Ubuntu: nothing to compare against, so the build
        // with the lowest C library floor goes first.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'linux', 'x86_64', 'debian-12'), [
            'ubuntu-22.04-x86_64',
            'ubuntu-24.04-x86_64',
        ]);
    });

    test('windows has one build and needs no ordering', () => {
        // A Windows host is always "unidentified" -- the builds are named after
        // runner images, which is not a version this machine has -- and that is
        // exactly why only one is published: a list of one needs no policy.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'windows', 'x86_64', undefined), [
            'windows-2022-x86_64',
        ]);
    });

    test('an unknown operating system has no candidates', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'freebsd', 'x86_64', undefined), []);
    });

    test('an architecture the release does not carry has no candidates', () => {
        // There is no macOS x86_64 bundle: nothing is offered, rather than an arm64 one.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'macos', 'x86_64', 'macos-15'), []);
    });

    test('a release with no manifest for this kind has no candidates', () => {
        assert.deepStrictEqual(
            selectPlatforms({ version: '0.7.177' }, 'bundle', 'linux', 'x86_64', 'ubuntu-24.04'),
            [],
        );
    });

    test('the IDE archives carry no OS version and are offered as they are', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'ide', 'linux', 'x86_64', 'ubuntu-22.04'), ['linux-x86_64']);
    });
});

// The report a user gets when there is no backend is only as good as this list:
// "no PartCAD service available" alone sent people looking in the wrong place,
// because the usual cause -- PartCAD installed in a Python environment whose
// `bin` is not on the PATH the extension host inherited -- is invisible from the
// message. `resolveServicePath` fills `searched` as it goes, so the two cannot
// drift apart the way a hand-written copy of the list would.
suite('Where the service was looked for', () => {
    const EXE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';

    let tmp: string;

    function fakeContext(): vscode.ExtensionContext {
        return {
            globalStorageUri: vscode.Uri.file(path.join(tmp, 'storage')),
        } as unknown as vscode.ExtensionContext;
    }

    async function pointServicePathAt(exe: string | undefined): Promise<void> {
        await vscode.workspace
            .getConfiguration('partcad')
            .update('servicePath', exe ?? '', vscode.ConfigurationTarget.Global);
    }

    // `resolveServicePath` looks in `$XDG_DATA_HOME/partcad` and in the home
    // directory before it reaches PATH, so on a machine with PartCAD installed
    // by `install.sh` it would return early and the search report would be one
    // entry long. Point both at the empty temporary directory for the duration:
    // what is under test is the report, not this machine.
    let savedXdg: string | undefined;
    let savedHome: string | undefined;

    setup(() => {
        tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-provision-'));
        savedXdg = process.env.XDG_DATA_HOME;
        savedHome = process.env.HOME;
        process.env.XDG_DATA_HOME = path.join(tmp, 'data');
        process.env.HOME = path.join(tmp, 'home');
    });

    function restore(name: string, value: string | undefined): void {
        if (value === undefined) {
            delete process.env[name];
        } else {
            process.env[name] = value;
        }
    }

    teardown(async () => {
        restore('XDG_DATA_HOME', savedXdg);
        restore('HOME', savedHome);
        await pointServicePathAt(undefined);
        fs.rmSync(tmp, { recursive: true, force: true });
    });

    test('every place tried is reported when nothing is found', async () => {
        await pointServicePathAt(undefined);
        const searched: string[] = [];
        resolveServicePath(fakeContext(), 'partcad', searched);

        assert.ok(searched.length >= 5, `expected every lookup to be named, got ${searched.length}: ${searched}`);
        assert.ok(
            searched.some((s) => s.includes('partcad.servicePath')),
            'the setting is the first thing checked and has to be named, set or not',
        );
        assert.ok(
            searched.some((s) => s.includes(path.join('.local', 'bin'))),
            'the ~/.local/bin launcher is checked and has to be named',
        );
        // The one that matters most: a user with PartCAD in a virtual
        // environment needs to be told which PATH was consulted, since it is not
        // the one their terminal has.
        assert.ok(
            searched.some((s) => s.startsWith('PATH')),
            'PATH is the last resort and has to be named',
        );
    });

    test('nothing is reported past the lookup that succeeded', async () => {
        const exe = path.join(tmp, EXE);
        fs.writeFileSync(exe, '');
        await pointServicePathAt(exe);

        const searched: string[] = [];
        assert.strictEqual(resolveServicePath(fakeContext(), 'partcad', searched), exe);
        assert.deepStrictEqual(
            searched.map((s) => s.includes('partcad.servicePath')),
            [true],
            'the setting resolved, so no later location was tried and none may be claimed',
        );
    });
});

// "Find installed PartCAD" asks for a directory rather than an executable, because a
// user who has just run `pip install partcad` knows where their environment is
// and not necessarily what the service is called. What counts as the right
// directory is the question this answers.
suite('Finding the service in a directory the user picked', () => {
    const EXE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';

    let tmp: string;

    function withService(...segments: string[]): string {
        const dir = path.join(tmp, ...segments);
        fs.mkdirSync(dir, { recursive: true });
        const exe = path.join(dir, EXE);
        fs.writeFileSync(exe, '');
        return exe;
    }

    setup(() => {
        tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-local-python-'));
    });

    teardown(() => {
        fs.rmSync(tmp, { recursive: true, force: true });
    });

    test('the directory holding the executable is what is asked for', () => {
        const exe = withService('bin');
        assert.strictEqual(serviceUnder(path.join(tmp, 'bin')), exe);
    });

    test('the environment root works too, on either layout', () => {
        // Picking the environment instead of its `bin` is the obvious near-miss,
        // and refusing it would send the user back to guess again.
        const posix = withService('venv', 'bin');
        assert.strictEqual(serviceUnder(path.join(tmp, 'venv')), posix);

        const windows = withService('winenv', 'Scripts');
        assert.strictEqual(serviceUnder(path.join(tmp, 'winenv')), windows);
    });

    test('a directory with no service in it is not accepted', () => {
        fs.mkdirSync(path.join(tmp, 'empty'));
        assert.strictEqual(serviceUnder(path.join(tmp, 'empty')), undefined);
        assert.strictEqual(serviceUnder(path.join(tmp, 'does-not-exist')), undefined);
    });

    test('a directory is not mistaken for the executable', () => {
        // `isFile` and not `existsSync`: a `partcad-json-rpc` directory would
        // otherwise be handed to the spawn as if it were a program.
        fs.mkdirSync(path.join(tmp, 'trap', EXE), { recursive: true });
        assert.strictEqual(serviceUnder(path.join(tmp, 'trap')), undefined);
    });
});
