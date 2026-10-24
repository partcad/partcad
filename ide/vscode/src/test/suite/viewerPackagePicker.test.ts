//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The field the Draft, Simulation and Analysis tabs name a package in: a combo
// box - a text field that is always filled in, with a list of quick choices
// under it, that takes any other name typed into it as well.
//
// The field runs in the webview and this suite in the extension host, which
// has no DOM, so it is given the handful of things 'dom.ts' and the field ask of
// an element. What is pinned is what is offered and marked, that the field
// always says something, and when a name is handed to the tab: chosen, entered,
// or left in the field - and never while it is being typed.
//

import * as assert from 'assert';

import { PackageChoice, PackagePicker, quickChoices, unaskedChoice } from '../../webview/packagePicker';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public tabIndex = -1;
    public type = '';
    public value = '';
    public spellcheck = true;
    public id = '';
    public readonly attributes: Record<string, string> = {};
    public readonly classList = {
        toggle: (name: string, on?: boolean) => {
            const names = this.className.split(' ').filter((existing) => existing && existing !== name);
            if (on ?? !this.className.split(' ').includes(name)) {
                names.push(name);
            }
            this.className = names.join(' ');
        },
    };
    public focused = 0;
    private readonly listeners: Record<string, ((event?: unknown) => void)[]> = {};

    constructor(public readonly tagName: string) {}

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public append(...children: FakeElement[]): void {
        children.forEach((child) => this.appendChild(child));
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(name: string, handler: (event?: unknown) => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    public focus(): void {
        this.focused += 1;
    }

    /** Raise an event the way the user would. */
    public fire(name: string, event?: unknown): void {
        (this.listeners[name] ?? []).forEach((handler) => handler(event));
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
        walk(this);
        return found;
    }
}

const MUJOCO = '//pub/feature/simulate/mujoco:mujoco';
const GAZEBO = '//pub/feature/simulate/gazebo:gazebo';
const CHOICES: PackageChoice[] = [
    { value: MUJOCO, configured: true, title: 'What it names', note: 'named by the simulation' },
    { value: GAZEBO, configured: false, title: 'Use it instead' },
];

function picker(): { field: PackagePicker; root: FakeElement; commits: string[] } {
    const commits: string[] = [];
    const field = new PackagePicker({
        label: 'Simulated by',
        title: 'The simulation plugin that runs it',
        className: 'simulation-plugin',
        onCommit: (value) => commits.push(value),
    });
    field.set(MUJOCO, CHOICES);
    return { field, root: field.element as unknown as FakeElement, commits };
}

const input = (root: FakeElement) => root.find('package-picker-input')[0];
const list = (root: FakeElement) => root.find('package-picker-list')[0];
const options = (root: FakeElement) =>
    root.find('package-picker-option').map((option) => option.find('package-picker-value')[0].textContent);

/** Type into the field, a keystroke's worth at a time as far as the field can tell. */
function type(root: FakeElement, text: string): void {
    const field = input(root);
    field.fire('focus');
    field.value = text;
    field.fire('input');
}

const key = (name: string) => ({ key: name, preventDefault: () => undefined });

suite('Digital Thread package field', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('every known package is offered, with the one used unasked marked, and first when it is none of them', () => {
        const matches = (value: string, named: string) => value === named;
        assert.deepStrictEqual(
            quickChoices([MUJOCO, GAZEBO], GAZEBO, matches, 'why', 'note').map((choice) => [
                choice.value,
                choice.configured,
                choice.note,
            ]),
            [
                [MUJOCO, false, undefined],
                [GAZEBO, true, 'note'],
            ],
        );
        const own = quickChoices([MUJOCO, GAZEBO], '//acme/sim:bullet', matches, 'why');
        assert.deepStrictEqual(
            own.map((choice) => [choice.value, choice.configured]),
            [
                ['//acme/sim:bullet', true],
                [MUJOCO, false],
                [GAZEBO, false],
            ],
        );
        assert.strictEqual(unaskedChoice(own)?.value, '//acme/sim:bullet');
        // Nothing used unasked: nothing is marked, and the first is what a tab starts on.
        assert.strictEqual(unaskedChoice(quickChoices([MUJOCO, GAZEBO], undefined, matches, 'why'))?.value, MUJOCO);
    });

    test('the field is always filled in, and is a combo box over the quick choices', () => {
        const { root } = picker();
        assert.strictEqual(input(root).value, MUJOCO);
        assert.strictEqual(input(root).attributes.role, 'combobox');
        assert.ok(input(root).className.includes('simulation-plugin'));
        assert.strictEqual(list(root).hidden, true);
        assert.deepStrictEqual(options(root), [MUJOCO, GAZEBO]);
        // The one used unasked says why; the one in use is the current one.
        assert.strictEqual(root.find('package-picker-note')[0].textContent, 'named by the simulation');
        assert.ok(root.find('package-picker-option')[0].className.includes('current'));
    });

    test('the arrow and Down show every choice, whatever the field says', () => {
        const { root } = picker();
        root.find('package-picker-toggle')[0].fire('click');
        assert.strictEqual(list(root).hidden, false);
        assert.deepStrictEqual(options(root), [MUJOCO, GAZEBO]);
        assert.strictEqual(input(root).attributes['aria-expanded'], 'true');

        input(root).fire('keydown', key('Escape'));
        assert.strictEqual(list(root).hidden, true);
        input(root).fire('keydown', key('ArrowDown'));
        assert.strictEqual(list(root).hidden, false);
        assert.deepStrictEqual(options(root), [MUJOCO, GAZEBO]);
    });

    test('typing narrows the choices to the ones that match, and hides a list with none', () => {
        const { root, commits } = picker();
        type(root, 'gaz');
        assert.deepStrictEqual(options(root), [GAZEBO]);
        assert.strictEqual(list(root).hidden, false);
        type(root, '//mine/sim:bullet');
        assert.strictEqual(list(root).hidden, true);
        // Nothing is handed to the tab while it is being typed.
        assert.deepStrictEqual(commits, []);
    });

    test('choosing from the list hands the choice over', () => {
        const { root, field, commits } = picker();
        root.find('package-picker-toggle')[0].fire('click');
        root.find('package-picker-option')[1].fire('mousedown', key(''));
        assert.deepStrictEqual(commits, [GAZEBO]);
        assert.strictEqual(input(root).value, GAZEBO);
        assert.strictEqual(field.current, GAZEBO);
        assert.strictEqual(list(root).hidden, true);
    });

    test('a name of any package is taken, entered or left in the field, once', () => {
        const { root, commits } = picker();
        type(root, '  //mine/sim:bullet ');
        input(root).fire('keydown', key('Enter'));
        assert.deepStrictEqual(commits, ['//mine/sim:bullet']);
        assert.strictEqual(input(root).value, '//mine/sim:bullet');
        // Leaving the field with nothing new in it hands nothing over again.
        input(root).fire('blur');
        assert.deepStrictEqual(commits, ['//mine/sim:bullet']);

        type(root, 'sim-gazebo:gazebo');
        input(root).fire('blur');
        assert.deepStrictEqual(commits, ['//mine/sim:bullet', 'sim-gazebo:gazebo']);
    });

    test('Up and Down move through the open list, and Enter takes the one reached', () => {
        const { root, commits } = picker();
        input(root).fire('keydown', key('ArrowDown'));
        input(root).fire('keydown', key('ArrowDown'));
        input(root).fire('keydown', key('ArrowDown'));
        assert.ok(root.find('package-picker-option')[1].className.includes('active'));
        input(root).fire('keydown', key('Enter'));
        assert.deepStrictEqual(commits, [GAZEBO]);
    });

    test('an emptied field, or Escape, puts back the name in use', () => {
        const { root, commits } = picker();
        type(root, '');
        input(root).fire('blur');
        assert.strictEqual(input(root).value, MUJOCO);

        type(root, '//half/typed');
        input(root).fire('keydown', key('Escape'));
        // The list was not open, so Escape is "never mind".
        assert.strictEqual(input(root).value, MUJOCO);
        assert.deepStrictEqual(commits, []);
    });

    test('what is being typed is left alone by an answer arriving, and anything else is not', () => {
        const { root, field } = picker();
        type(root, '//mine/sim');
        field.set(MUJOCO, CHOICES);
        assert.strictEqual(input(root).value, '//mine/sim');

        // Once it is left, the tab's answer is what the field says.
        input(root).fire('keydown', key('Escape'));
        input(root).fire('blur');
        field.set(GAZEBO, CHOICES);
        assert.strictEqual(input(root).value, GAZEBO);
        assert.strictEqual(field.current, GAZEBO);
    });
});
