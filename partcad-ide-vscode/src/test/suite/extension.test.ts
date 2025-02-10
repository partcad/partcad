import * as assert from 'assert';

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
import * as vscode from 'vscode';
// import * as partcadExtension from '../../extension';

suite('PartCAD VSCode Extension Test Suite', () => {
    suiteTeardown(() => {
        vscode.window.showInformationMessage('All tests done!');
    });

    test('Extension activation', async () => {
        const ext = vscode.extensions.getExtension('openvmp.partcad');
        assert.notStrictEqual(ext, undefined);
        await ext?.activate();
        assert.strictEqual(ext?.isActive, true);
    });

    test('Command registration', () => {
        const commands = vscode.commands.getCommands(true);
        commands.then((strings) => {
            assert.ok(strings.includes('partcad.restart'));
        });
    });
});
