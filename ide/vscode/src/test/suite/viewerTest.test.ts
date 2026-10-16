//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Test tab, Validation's first: every check 'pc test' runs, with a mark,
// and the one selected - what it found, what it left behind, what it is.
//
// The verdicts and the text are the daemon's ('partcad.test.report' and
// 'partcad.test.catalog'). What is pinned here is that this side draws them as
// they are - a check still running is neither passed nor failed, one that does
// not apply says so - opens on the check worth reading, and hands an artifact
// to whoever shows objects. And that the host asks the daemon what the tab asked.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { TestArtifact, TestData, TestResult } from '../../webview/messages';
import { TestView, defaultSelection, inline, markOf, summaryOf } from '../../webview/test';
import { PartcadViewer } from '../../viewer/PartcadViewer';

/** Just enough of an element for 'dom.ts' and the Test tab. */
class FakeElement {
    public readonly children: (FakeElement | string)[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public tabIndex = -1;
    public readonly attributes: Record<string, string> = {};
    public readonly listeners: Record<string, ((event: unknown) => void)[]> = {};
    public readonly classList = {
        add: (...names: string[]) => names.forEach((name) => this.toggleClass(name, true)),
        toggle: (name: string, on: boolean) => this.toggleClass(name, on),
    };

    constructor(public readonly tagName: string) {}

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public append(...children: (FakeElement | string)[]): void {
        this.children.push(...children);
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(type: string, listener: (event: unknown) => void): void {
        (this.listeners[type] ??= []).push(listener);
    }

    public click(): void {
        (this.listeners.click ?? []).forEach((listener) => listener({}));
    }

    public focus(): void {}

    /** Everything this element says, its children's text included. */
    public get text(): string {
        return (
            this.textContent + this.children.map((child) => (typeof child === 'string' ? child : child.text)).join('')
        );
    }

    private toggleClass(name: string, on: boolean): void {
        const classes = new Set(this.className.split(' ').filter((existing) => existing.length > 0));
        if (on) {
            classes.add(name);
        } else {
            classes.delete(name);
        }
        this.className = Array.from(classes).join(' ');
    }
}

/** Every element under 'root' whose class list holds 'className', in the order drawn. */
function find(root: FakeElement, className: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (node: FakeElement | string) => {
        if (typeof node === 'string') {
            return;
        }
        if (node.className.split(' ').includes(className)) {
            found.push(node);
        }
        node.children.forEach(walk);
    };
    walk(root);
    return found;
}

function result(name: string, status: TestResult['status'], extra: Partial<TestResult> = {}): TestResult {
    return {
        name,
        status,
        findings: [],
        artifacts: [],
        doc: {
            title: `The ${name} check`,
            applies: 'parts',
            blocks: [
                { type: 'paragraph', text: `What \`${name}\` asks.` },
                { type: 'heading', text: 'When it fails' },
                { type: 'list', items: ['Move it.'] },
            ],
        },
        ...extra,
    };
}

const OVERLAP: TestArtifact = {
    kind: 'assembly',
    package: '//pkg',
    name: 'gearbox/interference/a+b',
    title: "'a' and 'b'",
    desc: 'Where they overlap',
};

function data(running = false): TestData {
    return {
        object: '//pkg:gearbox',
        kind: 'assembly',
        verified: !running,
        tests: [
            result('cad', running ? null : 'passed'),
            result('shell', 'not-applicable', { findings: [{ level: 'info', text: 'an assembly is checked...' }] }),
            result('interference', running ? null : 'failed', {
                findings: running ? [] : [{ level: 'error', text: "'a' and 'b' share 5.000 mm^3" }],
                artifacts: running ? [] : [OVERLAP],
            }),
        ],
    };
}

suite('The Test tab', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a check is marked by its verdict, and neither passed nor failed while it runs', () => {
        assert.strictEqual(markOf(result('cad', 'failed'), false), 'failed');
        assert.strictEqual(markOf(result('cad', 'not-applicable'), true), 'not-applicable');
        assert.strictEqual(markOf(result('cad', null), true), 'pending');
        assert.strictEqual(markOf(result('cad', null), false), 'unknown');
    });

    test('the list says what came out, or how much is still running', () => {
        assert.strictEqual(summaryOf(data(), false), '1 failed, 1 passed, 1 not applicable');
        assert.strictEqual(summaryOf(data(true), true), 'Running 2 of 3 checks…');
    });

    test('it opens on the first failure, or else the first check that applies', () => {
        assert.strictEqual(defaultSelection(data().tests), 'interference');
        assert.strictEqual(defaultSelection([result('shell', 'not-applicable'), result('cad', 'passed')]), 'cad');
        assert.strictEqual(defaultSelection([]), undefined);
    });

    test('code in the text of a check is drawn as code', () => {
        const nodes = inline('Set `minVolume` lower.');
        assert.strictEqual(nodes[0], 'Set ');
        assert.strictEqual((nodes[1] as unknown as FakeElement).tagName, 'code');
        assert.strictEqual((nodes[1] as unknown as FakeElement).textContent, 'minVolume');
        assert.strictEqual(nodes[2], ' lower.');
    });

    test('every check is listed, the failure is opened, and its artifact is offered', () => {
        const shown: TestArtifact[] = [];
        const root = new FakeElement('div');
        const view = new TestView(root as unknown as HTMLElement, { onRun: () => {}, onShow: (a) => shown.push(a) });

        view.show(data(), false);

        const rows = find(root, 'test-row');
        assert.deepStrictEqual(
            rows.map((row) => row.className),
            ['test-row passed', 'test-row not-applicable', 'test-row failed selected'],
        );
        assert.strictEqual(view.selected, 'interference');
        const page = find(root, 'test-page')[0];
        assert.ok(page.text.includes("'a' and 'b' share 5.000 mm^3"));
        assert.ok(page.text.includes('pc test -f interference'));
        assert.ok(page.text.includes('When it fails'));

        const button = find(root, 'test-artifact')[0].children.find(
            (child) => typeof child !== 'string' && child.tagName === 'button',
        ) as FakeElement;
        button.click();
        assert.deepStrictEqual(shown, [OVERLAP]);
    });

    test('while the checks run, the reader keeps the check they chose', () => {
        const root = new FakeElement('div');
        const view = new TestView(root as unknown as HTMLElement, { onRun: () => {}, onShow: () => {} });

        view.show(data(true), true);
        view.select('cad');
        assert.ok(find(root, 'test-page')[0].text.includes('Running…'));
        assert.strictEqual((find(root, 'test-run')[0] as FakeElement).disabled, true);

        view.show(data(), false);
        assert.strictEqual(view.selected, 'cad');
        assert.strictEqual((find(root, 'test-run')[0] as FakeElement).disabled, false);
    });

    test('running the checks again takes back every verdict but "not applicable"', () => {
        const root = new FakeElement('div');
        const view = new TestView(root as unknown as HTMLElement, { onRun: () => {}, onShow: () => {} });
        view.show(data(), false);

        view.markRunning();

        assert.deepStrictEqual(
            find(root, 'test-row').map((row) => row.className.replace(' selected', '')),
            ['test-row pending', 'test-row not-applicable', 'test-row pending'],
        );
        assert.strictEqual(find(root, 'test-artifact').length, 0);
    });

    test('a failure before anything was listed can be tried again', () => {
        let runs = 0;
        const root = new FakeElement('div');
        const view = new TestView(root as unknown as HTMLElement, { onRun: () => (runs += 1), onShow: () => {} });

        view.showError('PartCAD is not connected');

        const button = find(root, 'test-run')[0];
        assert.strictEqual(button.hidden, false);
        assert.strictEqual(button.disabled, false);
        assert.strictEqual(button.textContent, 'Try again');
        button.click();
        assert.strictEqual(runs, 1);
    });

    test('a failure to run keeps the list and says why', () => {
        const root = new FakeElement('div');
        const view = new TestView(root as unknown as HTMLElement, { onRun: () => {}, onShow: () => {} });
        view.show(data(true), true);
        view.showError('PartCAD is not connected');
        assert.strictEqual(find(root, 'test-row').length, 3);
        assert.ok(find(root, 'test-page')[0].text.includes('PartCAD is not connected'));
    });
});

suite('The Digital Thread host, asked for the Test tab', () => {
    const sent: Record<string, unknown>[] = [];
    let registration: vscode.Disposable | undefined;

    suiteSetup(() => {
        registration = vscode.commands.registerCommand('partcad.testReport', (args: Record<string, unknown>) => {
            sent.push(args);
            return { object: '//pkg:gearbox', kind: 'assembly', verified: args.verify, tests: [] };
        });
    });

    suiteTeardown(() => registration?.dispose());

    test('asks the daemon about the object on screen, and whether to run the checks', async () => {
        const viewer = new PartcadViewer(vscode.Uri.file(__dirname));
        const host = viewer as unknown as {
            lastShow: unknown;
            fetchTab(message: Record<string, unknown>): Promise<void>;
        };
        host.lastShow = { type: 'show', name: 'gearbox', kind: 'assembly', package: '//pkg' };

        await host.fetchTab({ tab: 'test', token: 1, verify: false });
        await host.fetchTab({ tab: 'test', token: 2, verify: true });

        assert.deepStrictEqual(
            sent.map((args) => [args.pkg, args.name, args.kind, args.verify]),
            [
                ['//pkg', 'gearbox', 'assembly', false],
                ['//pkg', 'gearbox', 'assembly', true],
            ],
        );
        viewer.dispose();
    });
});
