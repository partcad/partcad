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
// know is a tab that can only answer "nothing to fill it with". What the part
// declares for all four is asked under the group's id, 'analysis', and comes
// back with the configured implementations beside it.
//
// And when a show arrives: the tab it asks for, and the scenario on that tab,
// reach the renderer as they came.
//
// And when the panel moves on - or the renderer starts over on the same
// object - what it asked for and will now drop is cancelled, not left running
// on the daemon.
//
// And when a colour, a material or a finish is opened: there is nothing for
// PartCAD to draw, so the host shows it itself, and its CMF tab asks the daemon
// by the kind, which is the only thing that finds a declaration.
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
        // No callout box said anything a render does not do anyway.
        assert.strictEqual(sent[0].withComponentNames, undefined);
        assert.strictEqual(sent[0].withPortNames, undefined);
        viewer.dispose();
    });

    test('passes the callout boxes on to the daemon', async () => {
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'logo', kind: 'assembly', package: '//pkg' };
        sent.length = 0;

        await host.fetchTab({
            tab: '2d',
            token: 2,
            format: 'svg',
            withPorts: true,
            withComponentNames: true,
            withComponentPrices: true,
            withMaterials: true,
            withPortNames: false,
            withInterfaceNames: false,
        });

        assert.strictEqual(sent.length, 1);
        assert.strictEqual(sent[0].withComponentNames, true);
        assert.strictEqual(sent[0].withComponentPrices, true);
        assert.strictEqual(sent[0].withMaterials, true);
        assert.strictEqual(sent[0].withPortNames, false);
        assert.strictEqual(sent[0].withInterfaceNames, false);
        viewer.dispose();
    });
});

suite('The Digital Thread host, asked what the components cost', () => {
    const asked: Record<string, unknown>[] = [];
    let registration: vscode.Disposable | undefined;

    suiteSetup(() => {
        registration = vscode.commands.registerCommand('partcad.componentPrices', (args: Record<string, unknown>) => {
            asked.push(args);
            // eslint-disable-next-line @typescript-eslint/naming-convention
            return { object: '//pkg:logo', prices: { '//pkg:bolt': { price: 0.25, currency: 'USD' } } };
        });
    });

    suiteTeardown(() => registration?.dispose());

    test("asks under the Design group's id, about the object on screen, and posts the answer back", async () => {
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'logo', kind: 'assembly', package: '//pkg' };
        host.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };

        await host.fetchTab({ tab: 'design', token: 7 });

        assert.strictEqual(asked.length, 1);
        assert.strictEqual(asked[0].pkg, '//pkg');
        assert.strictEqual(asked[0].name, 'logo');
        assert.strictEqual(asked[0].kind, 'assembly');
        const answer = posted.find((message) => message.type === 'tabData');
        assert.strictEqual(answer?.tab, 'design');
        assert.strictEqual(answer?.token, 7);
        assert.deepStrictEqual(answer?.data, {
            object: '//pkg:logo',
            // eslint-disable-next-line @typescript-eslint/naming-convention
            prices: { '//pkg:bolt': { price: 0.25, currency: 'USD' } },
        });
        viewer.dispose();
    });
});

suite('The Digital Thread host, asked where each material is', () => {
    const asked: Record<string, unknown>[] = [];
    let registration: vscode.Disposable | undefined;
    const cluster = { material: '//pkg:abs', name: 'abs', at: [5, 0, 0], nodes: [[0], [1]], faces: 12 };

    suiteSetup(() => {
        registration = vscode.commands.registerCommand('partcad.materialClusters', (args: Record<string, unknown>) => {
            asked.push(args);
            return { object: '//pkg:logo', distance: 10, clusters: [cluster] };
        });
    });

    suiteTeardown(() => registration?.dispose());

    test("asks under the 3D tab's id, about the object on screen, and posts the answer back", async () => {
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'logo', kind: 'assembly', package: '//pkg' };
        host.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };

        await host.fetchTab({ tab: '3d', token: 9 });

        assert.strictEqual(asked.length, 1);
        assert.strictEqual(asked[0].pkg, '//pkg');
        assert.strictEqual(asked[0].name, 'logo');
        assert.strictEqual(asked[0].kind, 'assembly');
        const answer = posted.find((message) => message.type === 'tabData');
        assert.strictEqual(answer?.tab, '3d');
        assert.strictEqual(answer?.token, 9);
        assert.deepStrictEqual(answer?.data, { object: '//pkg:logo', distance: 10, clusters: [cluster] });
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

    /** What 'cae.list' was asked with. */
    const listed: Record<string, unknown>[] = [];

    suiteSetup(() => {
        registrations.push(
            vscode.commands.registerCommand('partcad.cae', (args: Record<string, unknown>) => {
                sent.push(args);
                const entry = {
                    object: '//pkg:bracket',
                    analysis: args.analysis,
                    scenario: args.scenario,
                    implementation: args.implementation ?? defaults[args.analysis as string],
                    filepath: '/tmp/bracket.png',
                    extension: 'png',
                    content: '',
                    findings: [],
                    error: null,
                };
                return { object: '//pkg:bracket', analysis: args.analysis, analyses: [entry], findings: [] };
            }),
            vscode.commands.registerCommand('partcad.caeList', (args: Record<string, unknown>) => {
                listed.push(args);
                return {
                    object: '//pkg:bracket',
                    kind: 'part',
                    analyses: { fea: [{ name: 'loaded', implementation: null }], dynamic: [], thermal: [], cfd: [] },
                    errors: {},
                };
            }),
            vscode.commands.registerCommand('partcad.caeDefaults', () => defaults),
        );
    });

    suiteTeardown(() => registrations.forEach((registration) => registration.dispose()));

    /** A host showing the bracket, and everything it posts to its webview. */
    function bracket(): {
        viewer: PartcadViewer;
        host: { fetchTab(message: Record<string, unknown>): Promise<void> };
        posted: Record<string, unknown>[];
    } {
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
        return { viewer, host, posted };
    }

    test('runs the scenario asked for, of the analysis each tab is named after, overriding nothing it was not told to', async () => {
        sent.length = 0;
        const { viewer, host, posted } = bracket();

        let token = 0;
        for (const tab of ANALYSIS_TABS) {
            await host.fetchTab({ tab, token: ++token, scenario: 'loaded' });
        }
        // A typed implementation is the override 'pc cae <analysis> --implementation' is.
        await host.fetchTab({ tab: 'thermal', token: ++token, scenario: 'sunlit', implementation: '//mine:thermal' });

        // Without one, none is sent: the daemon runs the scenario with the one
        // it names, and failing that with the configured default. Sending the
        // default from here would outrank what the scenario names.
        assert.deepStrictEqual(
            sent.map((args) => [args.analysis, args.scenario, args.implementation, args.inline]),
            [
                ['fea', 'loaded', undefined, true],
                ['dynamic', 'loaded', undefined, true],
                ['thermal', 'loaded', undefined, true],
                ['cfd', 'loaded', undefined, true],
                ['thermal', 'sunlit', '//mine:thermal', true],
            ],
        );
        // Every answer goes back to the tab that asked, and none of them is a refusal.
        assert.deepStrictEqual(
            posted.map((message) => [message.tab, message.token, message.error]),
            [
                ['fea', 1, undefined],
                ['dynamic', 2, undefined],
                ['thermal', 3, undefined],
                ['cfd', 4, undefined],
                ['thermal', 5, undefined],
            ],
        );
        viewer.dispose();
    });

    test('asks what the part declares once, for all four, with the configured implementations beside it', async () => {
        listed.length = 0;
        const { viewer, host, posted } = bracket();

        await host.fetchTab({ tab: 'analysis', token: 7 });

        // With the token that cancels it if the panel moves on (see 'inFlight').
        assert.deepStrictEqual(
            listed.map(({ pkg, name }) => ({ pkg, name })),
            [{ pkg: '//pkg', name: 'bracket' }],
        );
        assert.ok(listed[0].cancellation);
        assert.strictEqual(posted.length, 1);
        assert.strictEqual(posted[0].tab, 'analysis');
        const data = posted[0].data as { analyses: Record<string, unknown[]>; defaults: Record<string, string> };
        assert.deepStrictEqual(Object.keys(data.analyses), ['fea', 'dynamic', 'thermal', 'cfd']);
        // The field over the model is pre-filled from these for a scenario that names none.
        assert.deepStrictEqual(data.defaults, defaults);
        viewer.dispose();
    });
});

suite('The Digital Thread host, shown something', () => {
    test('passes the tab and the scenario a show asks for on to the renderer, as they came', () => {
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as { panel: unknown };
        host.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };

        // 'pc ide view --analysis-fea --scenario dropped'.
        viewer.handle({
            type: 'show',
            name: 'bracket',
            kind: 'part',
            package: '//pkg',
            tab: 'fea',
            scenario: 'dropped',
            object: null,
        });
        // And a show that asks for neither, which says so rather than leaving them out.
        viewer.handle({ type: 'show', name: 'bracket', kind: 'part', package: '//pkg', object: null });

        assert.deepStrictEqual(
            posted.map((message) => [message.type, message.tab, message.scenario]),
            [
                ['show', 'fea', 'dropped'],
                ['show', null, null],
            ],
        );
        viewer.dispose();
    });
});

suite('The Digital Thread host, and the view panel', () => {
    /** A host showing the bracket, and everything it posts to its webview. */
    function bracket(): {
        viewer: PartcadViewer;
        host: {
            fetchTab(message: Record<string, unknown>): Promise<void>;
            showSection(token: number, section: unknown): Promise<void>;
        };
        posted: Record<string, unknown>[];
    } {
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
            showSection(token: number, section: unknown): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'bracket;length=10', kind: 'assembly', package: '//pkg' };
        host.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };
        return { viewer, host, posted };
    }

    test('a render carries where it is looked at from and what it is cut to', async () => {
        const sent: Record<string, unknown>[] = [];
        const registration = vscode.commands.registerCommand(
            'partcad.renderInline',
            (args: Record<string, unknown>) => {
                sent.push(args);
                return { object: '//pkg:bracket', format: 'png', filename: 'b.png', extension: 'png', content: '' };
            },
        );
        try {
            const { viewer, host } = bracket();
            await host.fetchTab({
                tab: '2d',
                token: 1,
                format: 'png',
                viewportOrigin: [0, 0, 100],
                viewportUp: [0, 1, 0],
                section: { z: [0, 5] },
            });
            assert.deepStrictEqual(sent[0].viewportOrigin, [0, 0, 100]);
            assert.deepStrictEqual(sent[0].viewportUp, [0, 1, 0]);
            assert.deepStrictEqual(sent[0].section, { z: [0, 5] });
            viewer.dispose();
        } finally {
            registration.dispose();
        }
    });

    test('a section of the 3D view is the object on screen shown again, cut, and answered once shown', async () => {
        const asked: Record<string, unknown>[] = [];
        let fail = false;
        const registration = vscode.commands.registerCommand('partcad.showSection', (args: Record<string, unknown>) => {
            asked.push(args);
            if (fail) {
                throw new Error('the boolean did not complete');
            }
            return null;
        });
        try {
            const { viewer, host, posted } = bracket();
            await host.showSection(7, { x: [0, 5] });
            // The name it was shown under, parameter values and all, and its kind.
            assert.deepStrictEqual(asked[0], {
                pkg: '//pkg',
                name: 'bracket;length=10',
                kind: 'assembly',
                section: { x: [0, 5] },
            });
            assert.deepStrictEqual(posted[posted.length - 1], { type: 'sectionShown', token: 7 });

            fail = true;
            await host.showSection(8, null);
            assert.deepStrictEqual(asked[1].section, null);
            assert.strictEqual(posted[posted.length - 1].token, 8);
            assert.ok(String(posted[posted.length - 1].error).includes('the boolean did not complete'));
            viewer.dispose();
        } finally {
            registration.dispose();
        }
    });

    test('a show says what it was cut to - absent from a PartCAD that cannot cut - as it came', () => {
        const { viewer, posted } = bracket();
        viewer.handle({ type: 'show', name: 'bracket', kind: 'part', package: '//pkg', object: null, section: null });
        viewer.handle({
            type: 'show',
            name: 'bracket',
            kind: 'part',
            package: '//pkg',
            object: null,
            section: { y: [0, 15] },
        });
        viewer.handle({ type: 'show', name: 'bracket', kind: 'part', package: '//pkg', object: null });
        assert.deepStrictEqual(
            posted.map((message) => message.section),
            [null, { y: [0, 15] }, undefined],
        );
        viewer.dispose();
    });
});

suite('The Digital Thread host, moving on', () => {
    /** The tokens each command was asked with, and a way to answer each call. */
    const asked: { command: string; token: vscode.CancellationToken; answer: () => void }[] = [];
    const registrations: vscode.Disposable[] = [];

    suiteSetup(() => {
        for (const command of ['partcad.bom', 'partcad.cae', 'partcad.supplyQuote']) {
            registrations.push(
                vscode.commands.registerCommand(
                    command,
                    (args: Record<string, unknown>) =>
                        new Promise((resolve) =>
                            asked.push({
                                command,
                                token: args.cancellation as vscode.CancellationToken,
                                answer: () => resolve({}),
                            }),
                        ),
                ),
            );
        }
        registrations.push(vscode.commands.registerCommand('partcad.caeDefaults', () => ({})));
    });

    suiteTeardown(() => registrations.forEach((registration) => registration.dispose()));

    function shown(): {
        viewer: PartcadViewer;
        host: { fetchTab(message: Record<string, unknown>): Promise<void> };
    } {
        asked.length = 0;
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'bracket', kind: 'part', package: '//pkg' };
        host.panel = { webview: { postMessage: () => Promise.resolve(true) }, dispose: () => undefined };
        return { viewer, host };
    }

    async function until(condition: () => boolean): Promise<void> {
        for (let i = 0; i < 500 && !condition(); i++) {
            await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.ok(condition());
    }

    test('a tab asked again cancels what it asked before, and nothing else', async () => {
        const { viewer, host } = shown();
        const first = host.fetchTab({ tab: 'bom', token: 1 });
        const other = host.fetchTab({ tab: 'supply', token: 2 });
        await until(() => asked.length === 2);
        const second = host.fetchTab({ tab: 'bom', token: 3 });
        await until(() => asked.length === 3);

        assert.strictEqual(asked[0].token.isCancellationRequested, true);
        assert.strictEqual(asked[1].token.isCancellationRequested, false);
        assert.strictEqual(asked[2].token.isCancellationRequested, false);
        asked.forEach((call) => call.answer());
        await Promise.all([first, other, second]);
        viewer.dispose();
    });

    test('another object cancels everything asked for the last one', async () => {
        const { viewer, host } = shown();
        const pending = [
            host.fetchTab({ tab: 'bom', token: 1 }),
            host.fetchTab({ tab: 'fea', token: 2, scenario: 'a' }),
        ];
        await until(() => asked.length === 2);
        viewer.handle({ type: 'show', name: 'nut', kind: 'part', package: '//pkg', object: null });

        assert.deepStrictEqual(
            asked.map((call) => call.token.isCancellationRequested),
            [true, true],
        );
        asked.forEach((call) => call.answer());
        await Promise.all(pending);
        viewer.dispose();
    });

    test('the same object posted again cancels everything asked for before it', async () => {
        // A webview that reloaded says 'ready', and one that lacked geometry it
        // was thought to hold says 'geometryMissing': either way it is posted
        // the show again, and starts over - asking again for what it wants.
        asked.length = 0;
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        let receive: ((message: Record<string, unknown>) => void) | undefined;
        const nothing = { dispose: () => undefined };
        const panel = {
            active: false,
            visible: false,
            webview: {
                options: {},
                html: '',
                cspSource: '',
                asWebviewUri: (uri: vscode.Uri) => uri,
                postMessage: () => Promise.resolve(true),
                onDidReceiveMessage: (listener: (message: Record<string, unknown>) => void) => {
                    receive = listener;
                    return nothing;
                },
            },
            onDidDispose: () => nothing,
            onDidChangeViewState: () => nothing,
            dispose: () => undefined,
        };
        viewer.restore(panel as unknown as vscode.WebviewPanel);
        viewer.handle({ type: 'show', name: 'bracket', kind: 'part', package: '//pkg', object: null });
        assert.ok(receive);

        for (const type of ['ready', 'geometryMissing']) {
            const before = asked.length;
            receive({ type: 'fetchTab', tab: 'bom', token: before + 1 });
            receive({ type: 'fetchTab', tab: 'supply', token: before + 2 });
            await until(() => asked.length === before + 2);
            receive({ type, digests: [] });

            assert.deepStrictEqual(
                asked.slice(before).map((call) => call.token.isCancellationRequested),
                [true, true],
                type,
            );
        }
        asked.forEach((call) => call.answer());
        viewer.dispose();
    });

    test('runs of an analysis do not replace one another', async () => {
        // A user who retypes the implementation and runs again has asked twice.
        const { viewer, host } = shown();
        const pending = [
            host.fetchTab({ tab: 'fea', token: 1, scenario: 'loaded' }),
            host.fetchTab({ tab: 'fea', token: 2, scenario: 'loaded', implementation: '//mine:fea' }),
        ];
        await until(() => asked.length === 2);

        assert.deepStrictEqual(
            asked.map((call) => call.token.isCancellationRequested),
            [false, false],
        );
        asked.forEach((call) => call.answer());
        await Promise.all(pending);
        viewer.dispose();
    });
});

suite('The Digital Thread host, and CMF', () => {
    const sent: Record<string, unknown>[] = [];
    let registration: vscode.Disposable | undefined;

    suiteSetup(() => {
        registration = vscode.commands.registerCommand('partcad.cmfInfo', (args: Record<string, unknown>) => {
            sent.push(args);
            return { object: `${args.pkg}:${args.name}`, kind: args.kind, items: [] };
        });
    });

    suiteTeardown(() => registration?.dispose());

    /** A host whose webview records what it is posted. */
    function host(): {
        viewer: PartcadViewer;
        internals: { lastShow: unknown; fetchTab(message: Record<string, unknown>): Promise<void> };
        posted: Record<string, unknown>[];
    } {
        const posted: Record<string, unknown>[] = [];
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const internals = viewer as unknown as {
            lastShow: unknown;
            panel: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        internals.panel = {
            webview: {
                postMessage: (message: Record<string, unknown>) => {
                    posted.push(message);
                    return Promise.resolve(true);
                },
            },
            dispose: () => undefined,
        };
        return { viewer, internals, posted };
    }

    test('a declaration is shown with no object, its package and its kind, and asks for no tab', () => {
        const { viewer, posted } = host();

        viewer.showDeclaration('//pkg', 'Medium Stone Grey', 'color');

        assert.strictEqual(posted.length, 1);
        const { type, name, kind, package: pkg, object, tab } = posted[0];
        assert.deepStrictEqual(
            { type, name, kind, pkg, object, tab },
            { type: 'show', name: 'Medium Stone Grey', kind: 'color', pkg: '//pkg', object: null, tab: null },
        );
        viewer.dispose();
    });

    test("the CMF tab asks about what is shown by its kind: a declaration's, or an object's", async () => {
        const { viewer, internals, posted } = host();

        viewer.showDeclaration('//pkg', 'satin', 'finish');
        await internals.fetchTab({ tab: 'cmf', token: 1 });
        internals.lastShow = { type: 'show', name: 'housing', kind: 'part', package: '//pkg' };
        await internals.fetchTab({ tab: 'cmf', token: 2 });
        // Shown by a PartCAD that did not say what it is: the daemon looks it up.
        internals.lastShow = { type: 'show', name: 'housing', package: '//pkg' };
        await internals.fetchTab({ tab: 'cmf', token: 3 });

        assert.deepStrictEqual(
            sent.map((args) => [args.pkg, args.name, args.kind]),
            [
                ['//pkg', 'satin', 'finish'],
                ['//pkg', 'housing', 'part'],
                ['//pkg', 'housing', undefined],
            ],
        );
        const answers = posted.filter((message) => message.type === 'tabData');
        assert.deepStrictEqual(
            answers.map((message) => [message.tab, message.token]),
            [
                ['cmf', 1],
                ['cmf', 2],
                ['cmf', 3],
            ],
        );
        viewer.dispose();
    });
});
