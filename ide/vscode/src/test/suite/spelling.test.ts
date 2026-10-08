//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// PartCAD's dictionary for Code Spell Checker (see `src/spelling.ts`).
//
// The first test needs nothing but the checkout: the dictionary is generated
// from the schemas, and it fails while the file shipped is not what the
// schemas generate today. The second needs the spell checker itself, which a
// plain `npm test` does not install; `.vscode-test.js` offers a run that does
// (`PARTCAD_TEST_WITH_CSPELL`), and without it the test says it was skipped.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { CSPELL_EXTENSION_ID } from '../../spelling';

function extensionPath(): string {
    const extension = vscode.extensions.getExtension('partcad.partcad-official');
    assert.ok(extension);
    return extension.extensionPath;
}

/**
 * The words the spell checker flags in ``document``, once they are ``expected`` or the time is up.
 *
 * Not the first findings it publishes: opening a PartCAD file is also what
 * activates this extension, so the spell checker can check the file once
 * before the dictionary reaches it, and then again after.
 */
async function flaggedWords(document: vscode.TextDocument, expected: string[], timeoutMs = 30000): Promise<string[]> {
    const deadline = Date.now() + timeoutMs;
    let flagged: string[] = [];
    for (;;) {
        flagged = vscode.languages
            .getDiagnostics(document.uri)
            .filter((d) => d.source === 'cSpell')
            .map((d) => document.getText(d.range));
        if (JSON.stringify(flagged) === JSON.stringify(expected) || Date.now() > deadline) {
            return flagged;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
    }
}

suite("PartCAD's spelling dictionary", () => {
    test('the dictionary is what the schemas generate', () => {
        const generate = require(path.join(extensionPath(), 'cspell', 'generate.js'));
        const shipped = fs.readFileSync(path.join(extensionPath(), 'cspell', 'partcad.txt'), 'utf8');
        assert.strictEqual(
            shipped.replace(/\r\n/g, '\n'),
            generate.render(generate.dictionary()),
            'cspell/partcad.txt is out of date: run `npm run cspell-dictionary`',
        );
    });

    test('the spell checker takes the words in PartCAD files and still finds a typo', async function () {
        if (vscode.extensions.getExtension(CSPELL_EXTENSION_ID) === undefined) {
            this.skip();
        }
        this.timeout(90000);
        const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-spelling-'));
        try {
            const file = path.join(directory, 'partcad.yaml');
            fs.writeFileSync(
                file,
                [
                    'desc: A packge of parts.',
                    'manufacturable: true',
                    'parts:',
                    '  bolt:',
                    '    type: cadquery',
                    '    connectPorts: {}',
                    '    countPerSku: 1',
                    '',
                ].join('\n'),
            );
            const document = await vscode.workspace.openTextDocument(file);
            await vscode.window.showTextDocument(document);
            assert.deepStrictEqual(await flaggedWords(document, ['packge']), ['packge']);
        } finally {
            await vscode.commands.executeCommand('workbench.action.closeAllEditors');
            fs.rmSync(directory, { recursive: true, force: true });
        }
    });
});
