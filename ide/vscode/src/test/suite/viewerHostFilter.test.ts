//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the extension host sends the daemon when the 2D or Draft tab asks for a
// render: the panel's filter and overlay have to reach 'render.inline' as the
// panel composed them, or the picture is of the whole object whatever is ticked.
//
// And when an Analysis tab asks for its analysis: the tab's id is the analysis
// 'cae.analyze' is asked for, so a tab the renderer draws and the host does not
// know is a tab that can only answer "nothing to fill it with".
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { PartcadViewer } from '../../viewer/PartcadViewer';
import { ANALYSIS_TABS } from '../../webview/messages';

suite('The Digital Thread host, asked to render', () => {
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

suite('The Digital Thread host, asked to analyse', () => {
    const sent: Record<string, unknown>[] = [];
    const registrations: vscode.Disposable[] = [];
    /** What 'cae.defaults' answers: the user configuration's implementation per analysis. */
    const defaults: Record<string, string> = {
        fea: '//pub/cae/calculix:fea',
        dynamic: '//pub/cae/calculix:dynamic',
        thermal: '//pub/cae/calculix:thermal',
        cfd: '//pub/cae/openfoam:cfd',
    };

    suiteSetup(() => {
        registrations.push(
            vscode.commands.registerCommand('partcad.cae', (args: Record<string, unknown>) => {
                sent.push(args);
                return {
                    object: '//pkg:bracket',
                    analysis: args.analysis,
                    implementation: args.implementation,
                    filepath: '/tmp/bracket.png',
                    extension: 'png',
                    content: '',
                    findings: [],
                };
            }),
            vscode.commands.registerCommand('partcad.caeDefaults', () => defaults),
        );
    });

    suiteTeardown(() => registrations.forEach((registration) => registration.dispose()));

    test('asks for the analysis each tab is named after, and says which implementation it used', async () => {
        sent.length = 0;
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'bracket', kind: 'part', package: '//pkg' };
        host.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };

        let token = 0;
        for (const tab of ANALYSIS_TABS) {
            await host.fetchTab({ tab, token: ++token });
        }
        // A typed implementation is the override 'pc cae <analysis> --implementation' is.
        await host.fetchTab({ tab: 'thermal', token: ++token, implementation: '//mine:thermal' });

        assert.deepStrictEqual(
            sent.map((args) => [args.analysis, args.implementation, args.inline]),
            [
                ['fea', defaults.fea, true],
                ['dynamic', defaults.dynamic, true],
                ['thermal', defaults.thermal, true],
                ['cfd', defaults.cfd, true],
                ['thermal', '//mine:thermal', true],
            ],
        );
        // Every answer carries the implementation back, to pre-fill the field
        // over the model with - and none of them is a refusal.
        assert.deepStrictEqual(
            posted.map((message) => [message.tab, message.implementation, message.error]),
            [
                ['fea', defaults.fea, undefined],
                ['dynamic', defaults.dynamic, undefined],
                ['thermal', defaults.thermal, undefined],
                ['cfd', defaults.cfd, undefined],
                ['thermal', '//mine:thermal', undefined],
            ],
        );
        viewer.dispose();
    });
});
