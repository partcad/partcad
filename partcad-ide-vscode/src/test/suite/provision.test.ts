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

import { selectPlatforms } from '../../common/provision';

const MANIFEST = {
    version: '0.7.177',
    bundle: {
        linux: {
            x86_64: ['ubuntu-24.04-x86_64', 'ubuntu-22.04-x86_64'],
            arm64: ['ubuntu-24.04-arm64', 'ubuntu-22.04-arm64'],
        },
        macos: { arm64: ['macos-26-arm64', 'macos-15-arm64'] },
        windows: { x86_64: ['windows-2025-x86_64', 'windows-2022-x86_64'] },
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
        // Windows, or a Linux that is not Ubuntu: nothing to compare against,
        // so the build with the lowest C library floor goes first.
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'windows', 'x86_64', undefined), [
            'windows-2022-x86_64',
            'windows-2025-x86_64',
        ]);
        assert.deepStrictEqual(selectPlatforms(MANIFEST, 'bundle', 'linux', 'x86_64', 'debian-12'), [
            'ubuntu-22.04-x86_64',
            'ubuntu-24.04-x86_64',
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
