//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The garage: where the Build vs Buy choices are kept, and the file name each
// object's choices go under - which the CLI has to arrive at too, from Python.
//

// The keys below are PartCAD object names ('//pkg:arm', ':gear'), which no
// naming convention is going to describe.
/* eslint-disable @typescript-eslint/naming-convention */

import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { bvbPath, escapeName, readChoices, writeChoices } from '../../common/garage';

suite('The garage', () => {
    let home: string;

    setup(() => {
        home = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-garage-'));
    });

    teardown(() => {
        fs.rmSync(home, { recursive: true, force: true });
    });

    test("an object's name is escaped as Python's quote(name, safe='') escapes it", () => {
        // Both expected values are what 'urllib.parse.quote' prints: the CLI
        // reads these files, and a file it cannot name is a choice it ignores.
        assert.strictEqual(escapeName('//pub/robots:arm'), '%2F%2Fpub%2Frobots%3Aarm');
        assert.strictEqual(escapeName("//pkg:a b*(x)!'~_.-é"), '%2F%2Fpkg%3Aa%20b%2A%28x%29%21%27~_.-%C3%A9');
    });

    test('the choices are kept under ~/.partcad/garage/default/bvb', () => {
        assert.strictEqual(
            bvbPath('//pkg:arm', home),
            path.join(home, '.partcad', 'garage', 'default', 'bvb', '%2F%2Fpkg%3Aarm.json'),
        );
    });

    test('what is written is read back, with the object it is for', () => {
        writeChoices('//pkg:arm', { '//pkg:bracket': 'build', '//pkg:motor': 'buy' }, home);

        assert.deepStrictEqual(readChoices('//pkg:arm', home), { '//pkg:bracket': 'build', '//pkg:motor': 'buy' });
        const stored = JSON.parse(fs.readFileSync(bvbPath('//pkg:arm', home), 'utf8'));
        assert.strictEqual(stored.object, '//pkg:arm');
        // Nothing left beside it from the write.
        assert.deepStrictEqual(fs.readdirSync(path.dirname(bvbPath('//pkg:arm', home))), ['%2F%2Fpkg%3Aarm.json']);
    });

    test('no file, a broken file and a value that is neither choice all read as no choice', () => {
        assert.deepStrictEqual(readChoices('//pkg:none', home), {});

        fs.mkdirSync(path.dirname(bvbPath('//pkg:broken', home)), { recursive: true });
        fs.writeFileSync(bvbPath('//pkg:broken', home), '{ not json');
        assert.deepStrictEqual(readChoices('//pkg:broken', home), {});

        fs.writeFileSync(
            bvbPath('//pkg:odd', home),
            JSON.stringify({ object: '//pkg:odd', choices: { '//pkg:a': 'steal', '//pkg:b': 'build' } }),
        );
        assert.deepStrictEqual(readChoices('//pkg:odd', home), { '//pkg:b': 'build' });
    });
});
