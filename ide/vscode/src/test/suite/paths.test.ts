//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Matching a path the editor reports against one PartCAD reports.
//

import * as assert from 'assert';
import * as path from 'path';

import { pathKey, workspacePath } from '../../common/paths';

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

suite('Showing a path PartCAD reports', () => {
    test('a path in the workspace is shown from the workspace folder', () => {
        assert.strictEqual(workspacePath('/home/me/pkg/partcad.yaml', ['/home/me/pkg'], 'linux'), './partcad.yaml');
        assert.strictEqual(
            workspacePath('/home/me/pkg/sub/partcad.yaml', ['/home/me/pkg'], 'linux'),
            './sub/partcad.yaml',
        );
    });

    test('every separator survives', () => {
        // What the Context view used to show: the daemon made the path relative
        // to its own working directory, '/', by replacing every occurrence of
        // it -- '.home.me.pkg.partcad.yaml'. Nothing here may do that again,
        // inside the workspace or outside it.
        assert.strictEqual(workspacePath('/home/me/pkg/partcad.yaml', ['/'], 'linux'), './home/me/pkg/partcad.yaml');
        assert.strictEqual(workspacePath('/home/me/pkg/partcad.yaml', [], 'linux'), '/home/me/pkg/partcad.yaml');
    });

    test('a path outside every folder is shown whole', () => {
        // Including a sibling whose name merely starts with the folder's.
        assert.strictEqual(
            workspacePath('/home/me/pkg2/partcad.yaml', ['/home/me/pkg'], 'linux'),
            '/home/me/pkg2/partcad.yaml',
        );
        assert.strictEqual(
            workspacePath('/home/me/other/partcad.yaml', ['/home/me/pkg'], 'linux'),
            '/home/me/other/partcad.yaml',
        );
    });

    test('the folder holding it is the one it is shown from', () => {
        assert.strictEqual(
            workspacePath('/home/me/two/partcad.yaml', ['/home/me/one', '/home/me/two'], 'linux'),
            './partcad.yaml',
        );
    });

    test('Windows spells it with its own separator and ignores the drive letter case', () => {
        // `Uri.fsPath` lower-cases the drive letter and PartCAD does not (see
        // `pathKey`), which must not put the package outside its own folder.
        assert.strictEqual(
            workspacePath('C:\\Users\\me\\pkg\\sub\\partcad.yaml', ['c:\\Users\\me\\pkg'], 'win32'),
            '.\\sub\\partcad.yaml',
        );
        assert.strictEqual(
            workspacePath('D:\\pkg\\partcad.yaml', ['c:\\Users\\me\\pkg'], 'win32'),
            'D:\\pkg\\partcad.yaml',
        );
    });

    test('what is not an absolute path is shown as it is', () => {
        // The placeholder before PartCAD answers, and an older service's
        // already-relative path: nothing here knows what it is relative to.
        assert.strictEqual(workspacePath('Loading...', ['/home/me/pkg'], 'linux'), 'Loading...');
        assert.strictEqual(workspacePath('./partcad.yaml', ['/home/me/pkg'], 'linux'), './partcad.yaml');
        assert.strictEqual(workspacePath('.\\partcad.yaml', ['c:\\pkg'], 'win32'), '.\\partcad.yaml');
    });
});
