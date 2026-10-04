//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Design tab's 2D and Draft panes: what they offer to render to, and when
// there is something to save.
//
// The pane runs in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the pane ask of an
// element - a <select> among them, which answers 'value' the way a browser's
// does. The picture itself is not drawn here ('image.ts' pans and zooms it, and
// is a browser's business); what is pinned is which file type a pane is on after
// its list changes under it, and that Save is offered exactly while there is a
// file to save.
//

import * as assert from 'assert';

import { RenderData } from '../../webview/messages';
import { RenderView } from '../../webview/render';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public readonly attributes: Record<string, string> = {};
    public readonly classList = {
        add: (...names: string[]) => {
            this.className = [...this.className.split(' ').filter(Boolean), ...names].join(' ');
        },
        remove: (...names: string[]) => {
            this.className = this.className
                .split(' ')
                .filter((name) => name && !names.includes(name))
                .join(' ');
        },
    };
    private ownValue = '';
    private chosen: string | undefined;
    private readonly listeners: Record<string, (() => void)[]> = {};

    constructor(public readonly tagName: string) {}

    /** An <option>'s own value, or what a <select> has selected - the first option until told otherwise. */
    public get value(): string {
        if (this.tagName !== 'select') {
            return this.ownValue;
        }
        const values = this.children.map((option) => option.value);
        return this.chosen !== undefined && values.includes(this.chosen) ? this.chosen : (values[0] ?? '');
    }

    public set value(value: string) {
        if (this.tagName === 'select') {
            this.chosen = value;
        } else {
            this.ownValue = value;
        }
    }

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public replaceChildren(): void {
        this.children.length = 0;
        this.chosen = undefined;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(name: string, handler: () => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    /** Raise an event the way the user would. */
    public fire(name: string): void {
        (this.listeners[name] ?? []).forEach((handler) => handler());
    }

    /** Everything under this element with this class, in the order it is drawn. */
    public find(className: string): FakeElement[] {
        const found: FakeElement[] = [];
        const walk = (element: FakeElement) => {
            if (element.className.split(' ').includes(className)) {
                found.push(element);
            }
            element.children.forEach(walk);
        };
        this.children.forEach(walk);
        return found;
    }

    public text(): string {
        return this.textContent + this.children.map((child) => child.text()).join('');
    }
}

interface Calls {
    change: number;
    plugins: string[];
    save: number;
}

function pane(options: { plugins?: string[]; formats?: { value: string; label: string }[] }): {
    root: FakeElement;
    view: RenderView;
    calls: Calls;
} {
    const root = new FakeElement('div');
    const calls: Calls = { change: 0, plugins: [], save: 0 };
    const view = new RenderView(root as unknown as HTMLElement, {
        ...options,
        onChange: () => (calls.change += 1),
        onPlugin: (plugin) => calls.plugins.push(plugin),
        onSave: () => (calls.save += 1),
    });
    return { root, view, calls };
}

const PICTURES = [
    { value: 'png', label: 'PNG' },
    { value: 'jpeg', label: 'JPEG' },
    { value: 'svg', label: 'SVG' },
];

const DRAWINGS = [
    { value: 'pdf', label: 'PDF' },
    { value: 'svg', label: 'SVG' },
    { value: 'dxf', label: 'DXF' },
];

function formatSelect(root: FakeElement): FakeElement {
    return root.find('render-select').filter((select) => !select.className.includes('render-plugin'))[0];
}

function saveButton(root: FakeElement): FakeElement {
    return root.find('render-save')[0];
}

function rendered(extension: string): RenderData {
    return { object: '//pkg:cube', format: extension, filename: `cube.${extension}`, extension, content: 'AAAA' };
}

suite('The 2D and Draft tabs', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('the 2D tab starts on the first picture format, and a change of it renders again', () => {
        const { root, view, calls } = pane({ formats: PICTURES });
        assert.strictEqual(view.format, 'png');
        assert.strictEqual(view.plugin, undefined);

        const select = formatSelect(root);
        select.value = 'svg';
        select.fire('change');

        assert.strictEqual(view.format, 'svg');
        assert.strictEqual(calls.change, 1);
    });

    test('a drawing starts on the format the pane can show, not on whichever is listed first', () => {
        const { view } = pane({ plugins: ['//pub/feature/render/draftwright'] });
        assert.strictEqual(view.format, undefined);

        view.setFormats(DRAWINGS, ['svg', 'png']);

        assert.strictEqual(view.format, 'svg');
    });

    test('a format the user chose is kept while the list still has it', () => {
        const { root, view } = pane({ plugins: ['//draw'] });
        view.setFormats(DRAWINGS, ['svg']);
        formatSelect(root).value = 'dxf';

        view.setFormats(DRAWINGS, ['svg']);
        assert.strictEqual(view.format, 'dxf');

        view.setFormats([{ value: 'pdf', label: 'PDF' }], ['svg']);
        assert.strictEqual(view.format, 'pdf');
    });

    test('no formats is no choice', () => {
        const { root, view } = pane({ plugins: ['//draw'] });
        view.setFormats([]);

        assert.strictEqual(view.format, undefined);
        assert.strictEqual(formatSelect(root).disabled, true);
    });

    test('the drawing package is offered, and choosing another asks what it draws', () => {
        const { root, view, calls } = pane({ plugins: ['//pub/feature/render/draftwright', '//other/draw'] });
        assert.strictEqual(view.plugin, '//pub/feature/render/draftwright');

        const plugins = root.find('render-plugin')[0];
        plugins.value = '//other/draw';
        plugins.fire('change');

        assert.deepStrictEqual(calls.plugins, ['//other/draw']);
        assert.strictEqual(view.plugin, '//other/draw');
    });

    test('Save is offered while there is a file, and only then', () => {
        const { root, view, calls } = pane({ formats: PICTURES });
        const save = saveButton(root);
        assert.strictEqual(save.disabled, true);

        view.show(rendered('pdf'));
        assert.strictEqual(save.disabled, false);
        save.fire('click');
        assert.strictEqual(calls.save, 1);

        view.setBusy('Rendering…');
        assert.strictEqual(save.disabled, true);

        view.show(rendered('pdf'));
        view.showError('It did not draw.');
        assert.strictEqual(save.disabled, true);
    });

    test('a file the browser cannot show is still one to save, and the pane says so', () => {
        const { root, view } = pane({ plugins: ['//draw'] });

        view.show(rendered('dxf'));

        const body = root.find('render-body')[0];
        assert.match(body.text(), /A \.dxf file can't be shown here\. Save it/);
        assert.strictEqual(saveButton(root).disabled, false);
    });
});
