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

import { pathKey } from '../../common/paths';
import { pathEntries, resolveServicePath, selectPlatforms, serviceUnder } from '../../common/provision';

const MANIFEST = {
    version: '0.7.177',
    bundle: {
        linux: {
            x86_64: ['ubuntu-24.04-x86_64', 'ubuntu-22.04-x86_64'],
            arm64: ['ubuntu-24.04-arm64', 'ubuntu-22.04-arm64'],
        },
        // Two arm64 entries and one x86_64. A release publishes one macOS build
        // per architecture today -- both frozen on macOS 15 -- but the policy
        // has to order a list of any length, macOS carried two before and will
        // again when the macOS 15 images retire, and no other operating system
        // here exercises "several builds of one arch, one of the other".
        macos: { arm64: ['macos-26-arm64', 'macos-15-arm64'], x86_64: ['macos-15-x86_64'] },
        // One Windows build, not one per image: nothing here can be compared
        // against a Windows host, and there is no floor for two builds to
        // differ in. See the note beside the matrix in "build-standalone.yml".
        windows: { x86_64: ['windows-2022-x86_64'] },
    },
    ide: {
        linux: { x86_64: ['linux-x86_64'] },
        macos: { arm64: ['macos-arm64'], x86_64: ['macos-x86_64'] },
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
        // There is no Windows arm64 bundle: nothing is offered, rather than an
        // x86_64 one that this machine would have to emulate.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'windows', 'arm64', undefined), []);
    });

    test('each macOS architecture is offered only its own builds', () => {
        // The two are separate lists in the manifest, so an Intel Mac is never
        // handed an Apple silicon bundle, and the shorter Intel list is no
        // reason to reach into the other one.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'macos', 'x86_64', 'macos-26'), ['macos-15-x86_64']);
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'macos', 'arm64', 'macos-15'), ['macos-15-arm64']);
    });

    test('a release with no manifest for this kind has no candidates', () => {
        assert.deepStrictEqual(
            selectPlatforms({ version: '0.7.177' }, 'bundle', 'linux', 'x86_64', 'ubuntu-24.04'),
            [],
        );
    });

    test('the IDE archives carry no OS version and are offered as they are', () => {
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'ide', 'linux', 'x86_64', 'ubuntu-22.04'), ['linux-x86_64']);
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'ide', 'macos', 'x86_64', 'macos-15'), ['macos-x86_64']);
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

    /**
     * Whether the report names `target`, however this platform spells it.
     *
     * Not `String.includes` on the paths as they come: the storage directory
     * reaches `resolveServicePath` as `globalStorageUri.fsPath`, and on Windows
     * `Uri.fsPath` lower-cases the drive letter -- so the report says
     * `c:\...\storage` where this test built `C:\...\storage`, and comparing
     * the two strings said the extension had not looked there. Which is the
     * very confusion `pathKey` exists for, arriving here by the same route it
     * arrives everywhere else.
     *
     * And not a substring match either: an entry has to *be* the directory or
     * be *inside* it. The report names the bundle root inside the storage
     * directory rather than the directory itself, so an exact comparison alone
     * would not do -- but a plain `includes` would let `<tmp>/storage-backup`
     * answer for `<tmp>/storage`, and a test that cannot tell those apart
     * cannot tell whether the extension looked where it said it did.
     */
    function names(searched: string[], target: string): boolean {
        const needle = pathKey(target);
        return searched.some((entry) => {
            const key = pathKey(entry);
            return key === needle || key.startsWith(needle + path.sep);
        });
    }

    // `resolveServicePath` looks at this platform's installation directory and
    // in the home directory before it reaches PATH, so on a machine with PartCAD
    // installed it would return early and the search report would be one entry
    // long. Point every variable those are derived from at the empty temporary
    // directory for the duration: what is under test is the report, not this
    // machine. `HOME` alone is not enough -- `os.homedir()` reads `USERPROFILE`
    // on Windows -- and neither is the home directory, since the Windows lookup
    // starts at `%LOCALAPPDATA%`.
    const SANDBOXED = ['XDG_DATA_HOME', 'HOME', 'USERPROFILE', 'LOCALAPPDATA'];
    let saved: Map<string, string | undefined>;

    setup(() => {
        tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-provision-'));
        saved = new Map(SANDBOXED.map((name) => [name, process.env[name]]));
        process.env.XDG_DATA_HOME = path.join(tmp, 'data');
        process.env.HOME = path.join(tmp, 'home');
        process.env.USERPROFILE = path.join(tmp, 'home');
        process.env.LOCALAPPDATA = path.join(tmp, 'local');
    });

    function restore(name: string, value: string | undefined): void {
        if (value === undefined) {
            delete process.env[name];
        } else {
            process.env[name] = value;
        }
    }

    teardown(async () => {
        saved.forEach((value, name) => restore(name, value));
        await pointServicePathAt(undefined);
        fs.rmSync(tmp, { recursive: true, force: true });
    });

    /**
     * The report `resolveServicePath` would produce on `platform`.
     *
     * Which places are searched depends on the platform, and a CI leg only ever
     * runs on one of them -- while the value of the report is precisely that it
     * names what *this* platform looked at. `process.platform` is an own
     * property of a plain object, so it can be made to say something else for
     * the length of one synchronous call and put back afterwards.
     */
    function searchedOn(platform: NodeJS.Platform): string[] {
        const original = process.platform;
        Object.defineProperty(process, 'platform', { value: platform, configurable: true });
        try {
            const searched: string[] = [];
            resolveServicePath(fakeContext(), 'partcad', searched);
            return searched;
        } finally {
            Object.defineProperty(process, 'platform', { value: original, configurable: true });
        }
    }

    test('every place tried is reported when nothing is found', async () => {
        await pointServicePathAt(undefined);
        const searched: string[] = [];
        resolveServicePath(fakeContext(), 'partcad', searched);

        assert.ok(searched.length >= 4, `expected every lookup to be named, got ${searched.length}: ${searched}`);
        assert.ok(
            searched.some((s) => s.includes('partcad.servicePath')),
            'the setting is the first thing checked and has to be named, set or not',
        );
        assert.ok(
            names(searched, path.join(tmp, 'storage')),
            "the extension's own download directory is checked and has to be named",
        );
        // The one that matters most: a user with PartCAD in a virtual
        // environment needs to be told which PATH was consulted, since it is not
        // the one their terminal has.
        assert.ok(
            searched.some((s) => s.startsWith('PATH')),
            'PATH is the last resort and has to be named',
        );
    });

    test("the POSIX lookup names install.sh's locations", async () => {
        await pointServicePathAt(undefined);
        const searched = searchedOn('linux');
        assert.ok(
            names(searched, path.join(tmp, 'data', 'partcad')),
            '$XDG_DATA_HOME/partcad is where install.sh puts a bundle and has to be named',
        );
        assert.ok(
            searched.some((s) => s.includes(path.join('.local', 'bin'))),
            'the ~/.local/bin launcher is checked and has to be named',
        );
    });

    test('the Windows lookup names Windows locations and no others', async () => {
        // Nothing installs to `~/.local/share` on Windows -- `install.sh` does
        // not run there -- so reporting it as searched sends a user looking in a
        // directory no installer of theirs has ever written to, which is the
        // opposite of what this list is for.
        await pointServicePathAt(undefined);
        const searched = searchedOn('win32');
        assert.ok(
            names(searched, path.join(tmp, 'local', 'PartCAD')),
            '%LOCALAPPDATA%\\PartCAD is where a Windows installation goes and has to be named',
        );
        assert.ok(
            !searched.some((s) => s.includes('.local')),
            'the POSIX locations are not searched on Windows and must not be reported as searched',
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

    // The extension's identity has moved twice -- publisher `OpenVMP` to
    // `PartCAD`, then name `partcad` to `partcad-official` -- and
    // `globalStorageUri` is named after that identity, so each move left every
    // bundle this extension had already downloaded in a directory it no longer
    // looks in. The symptom is the worst kind: a working installation reported
    // as missing, and downloaded again. Both old directories are searched, so
    // this runs for each.
    for (const identity of ['partcad.partcad', 'openvmp.partcad']) {
        test(`a bundle downloaded as ${identity} is still found`, async () => {
            await pointServicePathAt(undefined);

            const legacy = path.join(tmp, identity, 'partcad-bundle', '0.8.20');
            fs.mkdirSync(legacy, { recursive: true });
            const exe = path.join(legacy, EXE);
            fs.writeFileSync(exe, '');

            // Through `pathKey` for the reason `names` documents above: what
            // comes back is built from `globalStorageUri.fsPath`, whose drive
            // letter Windows lower-cases, while `tmp` here keeps the case it was
            // created with.
            assert.strictEqual(pathKey(resolveServicePath(fakeContext(), 'partcad') ?? ''), pathKey(exe));
        });

        // ...but only after the current one. `pc upgrade` and `downloadLatest`
        // install into the storage this extension owns now, so a bundle there is
        // by construction the newer of the two and a legacy root must not shadow
        // it.
        test(`the current storage wins over ${identity}`, async () => {
            await pointServicePathAt(undefined);

            for (const [dir, version] of [
                [path.join(tmp, identity, 'partcad-bundle'), '0.8.20'],
                [path.join(tmp, 'storage', 'partcad-bundle'), '0.8.19'],
            ]) {
                fs.mkdirSync(path.join(dir, version), { recursive: true });
                fs.writeFileSync(path.join(dir, version, EXE), '');
            }

            assert.strictEqual(
                pathKey(resolveServicePath(fakeContext(), 'partcad') ?? ''),
                pathKey(path.join(tmp, 'storage', 'partcad-bundle', '0.8.19', EXE)),
                'the legacy root is a fallback, not a candidate ranked by version',
            );
        });
    }

    // And in order between themselves: the name move is the more recent of the
    // two, so a bundle left by `partcad.partcad` is the newer thing to fall back
    // to and `openvmp.partcad` must not win over it.
    test('the newer of the two old identities is preferred', async () => {
        await pointServicePathAt(undefined);

        for (const [identity, version] of [
            ['partcad.partcad', '0.8.19'],
            ['openvmp.partcad', '0.8.20'],
        ]) {
            const dir = path.join(tmp, identity, 'partcad-bundle', version);
            fs.mkdirSync(dir, { recursive: true });
            fs.writeFileSync(path.join(dir, EXE), '');
        }

        assert.strictEqual(
            pathKey(resolveServicePath(fakeContext(), 'partcad') ?? ''),
            pathKey(path.join(tmp, 'partcad.partcad', 'partcad-bundle', '0.8.19', EXE)),
            'the legacy roots are ordered by how recent the identity is, not by version',
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

// A Windows PATH quotes an entry that contains a space, and the quotes belong to
// the variable rather than to the directory. Joining `partcad-json-rpc.exe` onto
// one produced a path that could not exist, so an installation in
// `C:\Program Files\...` was invisible to the last-resort lookup.
suite('Reading the PATH', () => {
    let savedPath: string | undefined;

    setup(() => {
        savedPath = process.env.PATH;
    });

    teardown(() => {
        if (savedPath === undefined) {
            delete process.env.PATH;
        } else {
            process.env.PATH = savedPath;
        }
    });

    test('a quoted entry is the directory inside the quotes', () => {
        process.env.PATH = ['"/opt/with space"', '/usr/bin'].join(path.delimiter);
        assert.deepStrictEqual(pathEntries(), ['/opt/with space', '/usr/bin']);
    });

    test('empty entries are not directories', () => {
        // A trailing delimiter is normal on Windows, and an empty entry means
        // the current directory to some shells -- never something to search
        // for an executable to run.
        process.env.PATH = ['/usr/bin', '', '  '].join(path.delimiter);
        assert.deepStrictEqual(pathEntries(), ['/usr/bin']);
    });

    test('an unset PATH has no entries', () => {
        delete process.env.PATH;
        assert.deepStrictEqual(pathEntries(), []);
    });
});
