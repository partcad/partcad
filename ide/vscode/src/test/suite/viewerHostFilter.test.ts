//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the extension host sends the daemon when the 2D or Draft tab asks for a
// render: the panel's filter and overlay have to reach 'render.inline' as the
// panel composed them, or the picture is of the whole object whatever is ticked.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { PartcadViewer } from '../../viewer/PartcadViewer';

suite('The PartCAD Viewer host, asked to render', () => {
    const sent: Record<string, unknown>[] = [];
    let registration: vscode.Disposable | undefined;

    suiteSetup(() => {
        registration = vscode.commands.registerCommand('partcad.renderInline', (args: Record<string, unknown>) => {
            sent.push(args);
            return { object: '//pkg:logo', format: 'svg', filename: 'logo.svg', extension: 'svg', content: '' };
        });
    });

    suiteTeardown(() => registration?.dispose());

    test('passes the panel filter and overlay on to the daemon', async () => {
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'logo', kind: 'assembly', package: '//pkg' };

        await host.fetchTab({
            tab: '2d',
            token: 1,
            format: 'svg',
            // eslint-disable-next-line @typescript-eslint/naming-convention
            filter: { head_half_1: {} },
            withPorts: true,
            ports: ['hold'],
        });

        assert.strictEqual(sent.length, 1);
        // eslint-disable-next-line @typescript-eslint/naming-convention
        assert.deepStrictEqual(sent[0].filter, { head_half_1: {} });
        assert.strictEqual(sent[0].withPorts, true);
        assert.deepStrictEqual(sent[0].ports, ['hold']);
        viewer.dispose();
    });
});
