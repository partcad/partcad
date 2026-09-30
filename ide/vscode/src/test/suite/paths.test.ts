//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Matching a path the editor reports against one PartCAD reports.
//

import * as assert from 'assert';
import * as path from 'path';

import { pathKey } from '../../common/paths';

suite('Comparing file paths', () => {
    test('a Windows drive letter compares in either case', () => {
        // The whole reason this exists: `Uri.fsPath` lower-cases the drive
        // letter and PartCAD does not, so the editor's spelling of a document
        // and the daemon's spelling of the same file are different strings.
        // `PartcadLint` compared them directly and never once matched, which
        // silently turned every scene into an assembly there.
        assert.strictEqual(
            pathKey('c:\\Users\\me\\pkg\\robot.assy', 'win32'),
            pathKey('C:\\Users\\me\\pkg\\robot.assy', 'win32'),
        );
    });

    test('case is folded on Windows and nowhere else', () => {
        assert.strictEqual(pathKey('C:\\Pkg\\Robot.assy', 'win32'), 'c:\\pkg\\robot.assy');
        // A case-sensitive filesystem has two different files here, and saying
        // otherwise would report findings about the wrong one.
        assert.notStrictEqual(pathKey('/pkg/Robot.assy', 'linux'), pathKey('/pkg/robot.assy', 'linux'));
    });

    test('a path is normalised before it is compared', () => {
        const direct = path.resolve('pkg', 'robot.assy');
        assert.strictEqual(pathKey(direct), pathKey(path.join('pkg', '.', 'sub', '..', 'robot.assy')));
    });

    test('different files still differ', () => {
        assert.notStrictEqual(pathKey('/pkg/robot.assy'), pathKey('/pkg/robot2.assy'));
    });
});
