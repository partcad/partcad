//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The panel's tab strips: which tab one opens on, as the object under it changes.
//
// Every group shows all its tabs always and disables the ones
// that do not apply, and a strip rebuilt for a new object has to land on a tab
// that can be opened: the one the user last opened while it still can be, and
// the first one that can otherwise. The strip runs in the webview and this suite
// in the extension host, so it is given the handful of DOM things it uses.
//

import * as assert from 'assert';

import { TabId } from '../../webview/messages';
import { TabSpec, Tabs } from '../../webview/tabs';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public hidden = false;
    public title = '';
    public readonly dataset: Record<string, string> = {};
    public readonly attributes: Record<string, string> = {};
    public readonly classList = {
        toggle: (name: string, on: boolean) => {
            const names = this.className.split(' ').filter((n) => n && n !== name);
            this.className = (on ? [...names, name] : names).join(' ');
        },
    };
    private readonly listeners: Record<string, (() => void)[]> = {};

    constructor(public readonly tagName: string) {}

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(name: string, handler: () => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    /**
     * What a click does. A tab that does not apply is not a disabled button -
     * that would take its tooltip away - so the click arrives, and the strip is
     * what refuses it.
     */
    public click(): void {
        (this.listeners.click ?? []).forEach((handler) => handler());
    }
}

/** A strip of FEA and CFD, and everything it announced. */
function strip(): { tabs: Tabs; bar: FakeElement; panes: Record<string, FakeElement>; opened: TabId[] } {
    const bar = new FakeElement('div');
    const opened: TabId[] = [];
    const tabs = new Tabs(bar as unknown as HTMLElement, (id) => opened.push(id));
    return { tabs, bar, panes: { fea: new FakeElement('div'), cfd: new FakeElement('div') }, opened };
}

function specs(panes: Record<string, FakeElement>, enabled: { fea: boolean; cfd: boolean }): TabSpec[] {
    return [
        { id: 'fea', label: 'FEA', pane: panes.fea as unknown as HTMLElement, disabled: !enabled.fea },
        {
            id: 'cfd',
            label: 'CFD',
            pane: panes.cfd as unknown as HTMLElement,
            disabled: !enabled.cfd,
            hint: 'No CFD here',
        },
    ];
}

function button(bar: FakeElement, label: string): FakeElement {
    return bar.children.find((child) => child.textContent === label) as FakeElement;
}

suite('The tab strips', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a strip opened the first time opens on its first enabled tab', () => {
        const { tabs, panes, opened } = strip();

        tabs.setTabs(specs(panes, { fea: false, cfd: true }));

        assert.strictEqual(tabs.current, 'cfd');
        assert.deepStrictEqual(opened, ['cfd']);
        assert.strictEqual(panes.fea.hidden, true);
        assert.strictEqual(panes.cfd.hidden, false);
    });

    test('every tab is shown, and the ones that do not apply cannot be opened', () => {
        const { tabs, bar, panes, opened } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: false }));

        assert.deepStrictEqual(
            bar.children.map((child) => [child.textContent, child.attributes['aria-disabled']]),
            [
                ['FEA', 'false'],
                ['CFD', 'true'],
            ],
        );
        assert.match(button(bar, 'CFD').className, /\bdisabled\b/);
        button(bar, 'CFD').click();
        tabs.select('cfd');
        assert.strictEqual(tabs.current, 'fea');
        assert.deepStrictEqual(opened, ['fea']);
    });

    test('a tab that does not apply says why when hovered, and one that does says nothing', () => {
        const { tabs, bar, panes } = strip();

        tabs.setTabs(specs(panes, { fea: true, cfd: false }));
        assert.strictEqual(button(bar, 'CFD').title, 'No CFD here');

        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(button(bar, 'CFD').title, '');
    });

    test('the tab last opened is opened again while it can be', () => {
        const { tabs, bar, panes, opened } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        button(bar, 'CFD').click();

        tabs.setTabs(specs(panes, { fea: true, cfd: true }));

        assert.strictEqual(tabs.current, 'cfd');
        // Announced again: a rebuilt strip is a new object, to be asked about anew.
        assert.deepStrictEqual(opened, ['fea', 'cfd', 'cfd']);
    });

    test('when the tab last opened no longer applies, the first one that does is opened', () => {
        const { tabs, bar, panes } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        button(bar, 'CFD').click();

        tabs.setTabs(specs(panes, { fea: true, cfd: false }));

        assert.strictEqual(tabs.current, 'fea');
        assert.strictEqual(panes.fea.hidden, false);
        assert.strictEqual(panes.cfd.hidden, true);
    });

    test('a strip where nothing applies opens nothing, and remembers what was open', () => {
        const { tabs, bar, panes, opened } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        button(bar, 'CFD').click();
        opened.length = 0;

        tabs.setTabs(specs(panes, { fea: false, cfd: false }));
        assert.strictEqual(tabs.current, undefined);
        assert.deepStrictEqual(opened, []);
        assert.strictEqual(panes.fea.hidden, true);
        assert.strictEqual(panes.cfd.hidden, true);

        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(tabs.current, 'cfd');
    });

    test('the tab clicked is opened again once it applies again, whatever was fallen back to meanwhile', () => {
        // The Manufacturing strip disables Buy for the moment it takes to learn
        // what is bought; a reader who was on Buy lands on Buy again.
        const { tabs, bar, panes } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        button(bar, 'CFD').click();

        tabs.setTabs(specs(panes, { fea: true, cfd: false }));
        assert.strictEqual(tabs.current, 'fea');
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(tabs.current, 'cfd');
    });

    test('a secondary tab is never opened for the user, only by a click', () => {
        const { tabs, bar, panes } = strip();
        const secondary = (fea: boolean) =>
            specs(panes, { fea: true, cfd: true }).map((spec) => ({
                ...spec,
                secondary: spec.id === 'fea' && fea,
            }));

        tabs.setTabs(secondary(true));
        assert.strictEqual(tabs.current, 'cfd');

        // Clicked, it opens - and the next object it is not secondary for opens
        // on it, because that is the tab the user chose.
        button(bar, 'FEA').click();
        assert.strictEqual(tabs.current, 'fea');
        tabs.setTabs(secondary(true));
        assert.strictEqual(tabs.current, 'cfd');
        tabs.setTabs(secondary(false));
        assert.strictEqual(tabs.current, 'fea');
    });

    test('a rebuild for the same object keeps the tab on screen, secondary or not', () => {
        const { tabs, bar, panes } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        button(bar, 'FEA').click();

        tabs.setTabs(
            specs(panes, { fea: true, cfd: true }).map((spec) => ({ ...spec, secondary: spec.id === 'fea' })),
            { keepCurrent: true },
        );
        assert.strictEqual(tabs.current, 'fea');
    });

    test('a group is enabled while any of its tabs is', () => {
        const panes = { fea: new FakeElement('div'), cfd: new FakeElement('div') };
        assert.strictEqual(Tabs.anyEnabled(specs(panes, { fea: false, cfd: true })), true);
        assert.strictEqual(Tabs.anyEnabled(specs(panes, { fea: false, cfd: false })), false);
    });
    test('a tab asked for from outside is opened on the next rebuild, and then forgotten', () => {
        // 'pc ide view --analysis-cfd': the show carries the tab, and the strip
        // is rebuilt for the object it brought.
        const { tabs, panes } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(tabs.current, 'fea');

        tabs.request('cfd');
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(tabs.current, 'cfd');
    });

    test('a tab asked for waits through a rebuild that does not offer it', () => {
        // The Manufacturing strip disables Buy until it knows what is bought: a
        // request for Buy lands on Buy when that answer arrives.
        const { tabs, panes } = strip();
        tabs.request('cfd');
        tabs.setTabs(specs(panes, { fea: true, cfd: false }));
        assert.strictEqual(tabs.current, 'fea');

        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        assert.strictEqual(tabs.current, 'cfd');
    });

    test('a tab asked for is opened even when it is secondary', () => {
        const { tabs, panes } = strip();
        const secondaryFea = specs(panes, { fea: true, cfd: true }).map((spec) => ({
            ...spec,
            secondary: spec.id === 'fea',
        }));
        tabs.request('fea');
        tabs.setTabs(secondaryFea);
        assert.strictEqual(tabs.current, 'fea');
    });

    test('a withdrawn request leaves behind what a click would have', () => {
        const { tabs, panes } = strip();
        tabs.setTabs(specs(panes, { fea: true, cfd: false }));
        tabs.request('cfd');
        tabs.request(undefined);
        tabs.setTabs(specs(panes, { fea: true, cfd: false }));
        tabs.setTabs(specs(panes, { fea: true, cfd: true }));
        // Still what the user is taken to want, as a click would be.
        assert.strictEqual(tabs.current, 'cfd');
    });
});
