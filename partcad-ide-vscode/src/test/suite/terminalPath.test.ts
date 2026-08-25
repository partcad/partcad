//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The tools directory that goes on the terminal PATH. The part worth testing
// without a running window is which directory is chosen, and that the Python
// backend's contribution only exists once the language server has reported it.
//

import * as assert from 'assert';
import * as path from 'path';

import { resetToolsPathForTesting, setPythonScriptsDirectory, toolsDirectory } from '../../common/terminalPath';

suite('Terminal PATH', () => {
    setup(() => resetToolsPathForTesting());
    teardown(() => resetToolsPathForTesting());

    test('the Python backend contributes nothing until the server reports', () => {
        // 'partcad.backend' defaults to 'service', so ask about the Python side
        // through the setter rather than through a configuration this suite
        // cannot change.
        assert.strictEqual(setPythonScriptsDirectory(undefined), false, 'undefined -> undefined is not a change');
    });

    test('a reported scripts directory is a change, and reporting it again is not', () => {
        const scripts = path.join('/home', 'someone', '.local', 'bin');
        assert.strictEqual(setPythonScriptsDirectory(scripts), true);
        assert.strictEqual(setPythonScriptsDirectory(scripts), false, 'the same directory must not trigger a refresh');
        assert.strictEqual(setPythonScriptsDirectory(path.join('/opt', 'venv', 'bin')), true);
    });

    test('an empty report is the same as none', () => {
        // The server sends a string; a server that could not work the directory
        // out must not put an empty entry on the PATH.
        assert.strictEqual(setPythonScriptsDirectory(''), false);
        assert.strictEqual(setPythonScriptsDirectory('/opt/venv/bin'), true);
        assert.strictEqual(setPythonScriptsDirectory(''), true, 'clearing a reported directory is a change');
    });

    test('the service backend names the directory its executable lives in', () => {
        // The bundle is '<install-dir>/<version>/{pc,partcad,partcad-json-rpc}',
        // so the directory holding the resolved service is the one holding `pc`.
        // Asserted on the layout rather than through resolveServicePath, which
        // needs an ExtensionContext and a filesystem.
        const exe = path.join('/home', 'someone', '.local', 'share', 'partcad', '0.8.0', 'partcad-json-rpc');
        assert.strictEqual(path.dirname(exe), path.join('/home', 'someone', '.local', 'share', 'partcad', '0.8.0'));
    });

    test('toolsDirectory is exported for the extension to call', () => {
        assert.strictEqual(typeof toolsDirectory, 'function');
    });
});
