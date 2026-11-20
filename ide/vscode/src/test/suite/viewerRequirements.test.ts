//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Requirements tab: which mark each requirement gets, how the list is
// grouped, and what each feature says it is validated by.
//
// The verdicts are the daemon's ('partcad.requirements', the code 'pc qual test -f
// requirements' runs). What is pinned here is that this side draws them as
// they are - a requirement not yet measured is neither green nor red - and that
// every feature offers the LLM, with the tooltip naming the skill.
//

// The keys of what the daemon sends and is sent are the YAML's and the JSON-RPC's own.
/* eslint-disable @typescript-eslint/naming-convention */

import * as assert from 'assert';

import { RequirementCheck, RequirementEdit, RequirementsData } from '../../webview/messages';
import {
    LLM_HINT,
    PROBLEMS,
    RequirementsView,
    bannersOf,
    editFrom,
    formFields,
    groupChecks,
    markOf,
    prefill,
    removalOf,
    summary,
    writtenAt,
} from '../../webview/requirements';

/** Just enough of an element for 'dom.ts'. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public type = '';
    public value = '';
    public placeholder = '';
    public spellcheck = true;
    public readonly attributes: Record<string, string> = {};
    public readonly listeners: Record<string, (() => void)[]> = {};

    public addEventListener(event: string, listener: () => void): void {
        (this.listeners[event] ??= []).push(listener);
    }

    /** What a person does: a click, or typing into a field. */
    public fire(event: string): void {
        (this.listeners[event] ?? []).forEach((listener) => listener());
    }
    public readonly classList = {
        add: (...names: string[]) => {
            const classes = new Set(this.className.split(' ').filter((name) => name.length > 0));
            names.forEach((name) => classes.add(name));
            this.className = Array.from(classes).join(' ');
        },
    };

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
}

/** Every element under 'root' whose class list holds 'className', in the order drawn. */
function find(root: FakeElement, className: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (node: FakeElement) => {
        if (node.className.split(' ').includes(className)) {
            found.push(node);
        }
        node.children.forEach(walk);
    };
    walk(root);
    return found;
}

function check(section: string, name: string, passed: boolean | null): RequirementCheck {
    return { section, name, requirement: 'present', passed, detail: passed === false ? 'missing' : null };
}

/** What the object's own declaration holds, as 'requirements.check' says it: what the forms are filled from. */
const SECTION = {
    features: { stands: 'Does not tip over', pretty: 'Looks good' },
    ports: { top: { direction: [0, 0, -1], sketch: 'm3' } },
    interfaces: { m3: { left: { position: [0, 0, '>=5'] } }, m4: [null, [0, 0, 1], null] },
    physics: { mass: '>0,<=0.05', centerOfMass: [null, null, '<5'], inertia: { ixx: '>0' } },
    match: { ':old': { mass: 5, volume: '10%' } },
    has_private_dependencies: false,
};

/** A part whose requirements can be changed here. */
function editable(overrides: Partial<RequirementsData> = {}): RequirementsData {
    return data({
        section: SECTION,
        declared: SECTION,
        editable: null,
        physics_fields: { mass: 'value', centerOfMass: 'vector', inertia: ['ixx', 'iyy'] },
        has_names: ['color', 'material', 'private_dependencies'],
        requirements: [
            { ...check('physics', 'mass', true), address: { requirement: 'physics', name: 'mass' } },
            { ...check('ports', 'top', false), address: { requirement: 'port', name: 'top' } },
            {
                ...check('match', 'mass of :old', true),
                address: { requirement: 'match', name: ':old', amount: 'mass' },
            },
            // A 'feature:' that names nothing: no one requirement, so nothing to edit.
            check('sim', 'upright', false),
        ],
        ...overrides,
    });
}

function data(overrides: Partial<RequirementsData> = {}): RequirementsData {
    return {
        object: '//pkg:bracket',
        kind: 'part',
        defined: true,
        verified: true,
        features: [
            { name: 'stands', desc: 'Does not tip over', simulations: ['upright'] },
            { name: 'pretty', desc: 'Looks good', simulations: [] },
            {
                name: 'carries-a-shelf',
                desc: 'Holds a full shelf',
                simulations: [],
                analyses: [
                    { analysis: 'fea', name: 'loaded' },
                    { analysis: 'thermal', name: 'sunlit' },
                ],
            },
        ],
        requirements: [
            check('physics', 'mass', true),
            check('ports', 'top', false),
            check('sim', 'upright', false),
            check('interfaces', 'm3', true),
            check('fea', 'dropped', false),
        ],
        ...overrides,
    };
}

suite('The Requirements tab', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a requirement is green when met, red when not, and neither until it has been measured', () => {
        assert.strictEqual(markOf(check('ports', 'top', true)), 'pass');
        assert.strictEqual(markOf(check('ports', 'top', false)), 'fail');
        assert.strictEqual(markOf(check('ports', 'top', null)), 'pending');
    });

    test('the measured sections are listed in a fixed order, and anything else after them', () => {
        const groups = groupChecks(data().requirements);

        assert.deepStrictEqual(
            groups.map((group) => [group.heading, group.checks.map((item) => item.name)]),
            [
                ['Ports', ['top']],
                ['Interfaces', ['m3']],
                ['Physics', ['mass']],
                // A scenario naming a feature nobody declared is a problem too.
                [PROBLEMS, ['upright', 'dropped']],
            ],
        );
    });

    test('a match with another object is a measured section of its own, after the physics', () => {
        const groups = groupChecks([
            check('match', 'mass of :bracket', false),
            check('physics', 'mass', true),
            check('match', 'volume of :bracket', true),
        ]);

        assert.deepStrictEqual(
            groups.map((group) => [group.heading, group.checks.map((item) => item.name)]),
            [
                ['Physics', ['mass']],
                ['Matches', ['mass of :bracket', 'volume of :bracket']],
            ],
        );
    });

    test('the yes-or-no requirements are a measured section of their own, after the matches', () => {
        const groups = groupChecks([
            check('has', 'has_material', false),
            check('match', 'mass of :bracket', true),
            check('has', 'has_weight', true),
        ]);

        assert.deepStrictEqual(
            groups.map((group) => [group.heading, group.checks.map((item) => item.name)]),
            [
                ['Matches', ['mass of :bracket']],
                ['Specified', ['has_material', 'has_weight']],
            ],
        );
    });

    test('a feature lists the simulations that name it, and always the LLM last, with the skill as its tooltip', () => {
        const [stands, pretty] = data().features;

        assert.deepStrictEqual(
            bannersOf(stands).map((banner) => [banner.label, banner.kind]),
            [
                ['upright', 'simulation'],
                ['LLM', 'llm'],
            ],
        );
        assert.deepStrictEqual(
            bannersOf(pretty).map((banner) => banner.label),
            ['LLM'],
        );
        assert.strictEqual(bannersOf(pretty)[0].title, 'Validate using /pc-validate');
        assert.strictEqual(LLM_HINT, 'Validate using /pc-validate');
    });

    test('a feature lists the analysis scenarios that demonstrate it, after the simulations and before the LLM', () => {
        const feature = {
            name: 'carries-a-shelf',
            desc: 'Holds a full shelf',
            simulations: ['upright'],
            analyses: [
                { analysis: 'fea', name: 'loaded' },
                { analysis: 'thermal', name: 'sunlit' },
                // From a PartCAD that runs an analysis this extension has no tab for yet.
                { analysis: 'acoustic', name: 'hum' },
            ],
        };

        assert.deepStrictEqual(
            bannersOf(feature).map((banner) => [banner.label, banner.kind]),
            [
                ['upright', 'simulation'],
                ['FEA: loaded', 'analysis'],
                ['Heat Transfer: sunlit', 'analysis'],
                ['acoustic: hum', 'analysis'],
                ['LLM', 'llm'],
            ],
        );
        // The tooltip is the command that runs it, by the analysis's own id.
        assert.strictEqual(
            bannersOf(feature)[1].title,
            "Demonstrated by the FEA scenario 'loaded' (pc cae fea -f loaded)",
        );
        assert.strictEqual(
            bannersOf(feature)[2].title,
            "Demonstrated by the Heat Transfer scenario 'sunlit' (pc cae thermal -f sunlit)",
        );
        // A daemon from before analyses had scenarios says nothing of them.
        assert.deepStrictEqual(
            bannersOf({ name: 'stands', desc: '', simulations: [] }).map((banner) => banner.kind),
            ['llm'],
        );
    });

    test('the line over the lists says how it stands', () => {
        assert.strictEqual(summary(data(), false), '2 of 5 requirements are met.');
        assert.strictEqual(
            summary(data({ requirements: [check('ports', 'top', true)] }), false),
            'The requirement is met.',
        );
        assert.strictEqual(
            summary(data({ verified: false, requirements: [check('ports', 'top', null)] }), true),
            'Checking the model against what is required…',
        );
        assert.match(summary(data({ requirements: [] }), false), /Nothing here is for PartCAD to measure/);
        assert.match(summary(data({ requirements: [] }), false), /by a simulation or an analysis/);
    });

    test('drawn, every requirement has its mark and every feature its banners', () => {
        const root = new FakeElement('div');
        const view = new RequirementsView(root as unknown as HTMLElement);

        view.show(data(), false);

        assert.deepStrictEqual(
            find(root, 'mark').map((mark) => [mark.className, mark.textContent]),
            [
                ['mark fail', '✗'],
                ['mark pass', '✓'],
                ['mark pass', '✓'],
                ['mark fail', '✗'],
                ['mark fail', '✗'],
            ],
        );
        const banners = find(root, 'banner');
        assert.deepStrictEqual(
            banners.map((banner) => banner.textContent),
            ['upright', 'LLM', 'LLM', 'FEA: loaded', 'Heat Transfer: sunlit', 'LLM'],
        );
        assert.deepStrictEqual(
            find(root, 'analysis').map((banner) => banner.className),
            ['banner analysis', 'banner analysis'],
        );
        assert.deepStrictEqual(
            find(root, 'llm').map((banner) => banner.title),
            [LLM_HINT, LLM_HINT, LLM_HINT],
        );
    });

    test('an object with features alone draws no list of checks', () => {
        const root = new FakeElement('div');
        const view = new RequirementsView(root as unknown as HTMLElement);

        view.show(data({ requirements: [] }), false);

        assert.deepStrictEqual(find(root, 'mark'), []);
        assert.strictEqual(find(root, 'requirement-features').length, 1);
    });
    test('a form is filled from what the declaration holds, in whichever shape it was written', () => {
        const part = editable();
        assert.deepStrictEqual(prefill(part, { requirement: 'port', name: 'top' }), {
            name: 'top',
            angle: '',
            'position.x': '',
            'position.y': '',
            'position.z': '',
            'direction.x': '0',
            'direction.y': '0',
            'direction.z': '-1',
            sketch: 'm3',
        });
        assert.strictEqual(
            prefill(part, { requirement: 'interface', name: 'm3', instance: 'left' })['position.z'],
            '>=5',
        );
        // Any instance at a location: written as '[position, direction, angle]'.
        assert.strictEqual(prefill(part, { requirement: 'interface', name: 'm4' })['direction.z'], '1');
        assert.strictEqual(prefill(part, { requirement: 'physics', name: 'inertia.ixx' }).value, '>0');
        assert.strictEqual(prefill(part, { requirement: 'physics', name: 'centerOfMass' })['vector.z'], '<5');
        assert.deepStrictEqual(prefill(part, { requirement: 'match', name: ':old' }), {
            name: ':old',
            volume: '10%',
            displacement: '',
            mass: '5',
        });
        assert.deepStrictEqual(prefill(part, { requirement: 'has', name: 'has_private_dependencies' }), {
            name: 'private_dependencies',
            required: 'false',
        });
        assert.strictEqual(writtenAt(part, { requirement: 'port', name: 'side' }), undefined);
    });

    test('a form is sent as typed, for the daemon to read as partcad.yaml is read; prose as it is', () => {
        const part = editable();
        assert.deepStrictEqual(editFrom('physics', { name: 'mass', value: ' >1 ' }, part), {
            op: 'add',
            requirement: 'physics',
            name: 'mass',
            text: true,
            replace: false,
            value: '>1',
        });
        assert.deepStrictEqual(
            (editFrom('physics', { name: 'centerOfMass', 'vector.z': '<5' }, part) as RequirementEdit).value,
            ['', '', '<5'],
        );
        assert.deepStrictEqual(
            editFrom('port', { name: 'top', 'direction.x': '0', 'direction.y': '0', 'direction.z': '-1' }, part, {
                requirement: 'port',
                name: 'top',
            }),
            {
                op: 'add',
                requirement: 'port',
                name: 'top',
                text: true,
                replace: true,
                value: { direction: ['0', '0', '-1'] },
            },
        );
        const feature = editFrom('feature', { name: 'fits', desc: 'Fits: a 20 mm slot' }, part) as RequirementEdit;
        assert.strictEqual(feature.text, false);
        assert.strictEqual(feature.value, 'Fits: a 20 mm slot');
        assert.deepStrictEqual(
            (editFrom('interface', { name: 'm3', instance: 'right' }, part) as RequirementEdit).instances,
            ['right'],
        );
        assert.deepStrictEqual(editFrom('has', { name: 'material', required: 'false' }, part), {
            op: 'add',
            requirement: 'has',
            name: 'material',
            text: false,
            replace: false,
            value: false,
        });
    });

    test('a form that says too little is answered here, and sends nothing', () => {
        const part = editable();
        assert.match(editFrom('physics', { name: '' }, part) as string, /name is empty/);
        assert.match(editFrom('physics', { name: 'mass', value: '' }, part) as string, /value is empty/);
        assert.match(editFrom('match', { name: ':old' }, part) as string, /how closely/);
        assert.match(editFrom('feature', { name: 'fits' }, part) as string, /description is empty/);
    });

    test('a row is removed by what it is about: one instance, one amount, a feature with what names it', () => {
        assert.deepStrictEqual(removalOf({ requirement: 'interface', name: 'm3', instance: 'left' }), {
            op: 'remove',
            requirement: 'interface',
            name: 'm3',
            instances: ['left'],
        });
        assert.deepStrictEqual(removalOf({ requirement: 'match', name: ':old', amount: 'mass' }).amounts, ['mass']);
        assert.strictEqual(removalOf({ requirement: 'feature', name: 'stands' }, true).with_references, true);
    });

    test('the physical properties are offered as the daemon lists them, a member of a mapping on its own', () => {
        const [property] = formFields('physics', editable(), false);
        assert.deepStrictEqual(property.options, ['mass', 'centerOfMass', 'inertia.ixx', 'inertia.iyy']);
        assert.strictEqual(formFields('physics', editable(), true)[0].fixed, true);
        assert.deepStrictEqual(formFields('has', editable(), false)[0].options, [
            'color',
            'material',
            'private_dependencies',
        ]);
    });

    test('an object whose requirements can be changed offers every kind, and each row its buttons', () => {
        const root = new FakeElement('div');
        const sent: RequirementEdit[] = [];
        const view = new RequirementsView(root as unknown as HTMLElement, { onEdit: (edit) => sent.push(edit) });

        view.show(editable(), false);

        assert.deepStrictEqual(
            find(root, 'requirements-add')[0]
                .children.slice(1)
                .map((button) => button.textContent),
            ['Feature', 'Port', 'Interface', 'Physics', 'Match', 'Specified'],
        );
        // Each check that is one requirement can be edited and removed; the one that is not, neither.
        const rows = find(root, 'requirement');
        const buttons = rows.map((row) => find(row, 'small').map((button) => button.textContent));
        assert.deepStrictEqual(buttons, [['Edit', 'Remove'], ['Edit', 'Remove'], ['Edit', 'Remove'], []]);

        // Remove on the match's row removes that amount.
        find(rows[2], 'small')[1].fire('click');
        assert.deepStrictEqual(sent, [{ op: 'remove', requirement: 'match', name: ':old', amounts: ['mass'] }]);
        // And nothing more is sent until the answer is in.
        assert.ok(find(root, 'small').every((button) => button.disabled));
        view.edited("matching the mass of ':old'");
        assert.strictEqual(find(root, 'requirements-note')[0].textContent, "Changed: matching the mass of ':old'.");
    });

    test('a feature something names is removed only once the reader agrees to remove both', () => {
        const root = new FakeElement('div');
        const sent: RequirementEdit[] = [];
        const view = new RequirementsView(root as unknown as HTMLElement, { onEdit: (edit) => sent.push(edit) });
        view.show(editable(), false);

        const stands = find(find(root, 'requirement-features')[0], 'small');
        stands[1].fire('click');
        assert.deepStrictEqual(sent, []);
        const both = find(root, 'requirements-button').find((button) => button.textContent === 'Remove both');
        assert.ok(both);
        both.fire('click');
        assert.deepStrictEqual(sent, [{ op: 'remove', requirement: 'feature', name: 'stands', with_references: true }]);
    });

    test('an edit is saved from the form it opens, and a refusal keeps the form as typed', () => {
        const root = new FakeElement('div');
        const sent: RequirementEdit[] = [];
        const view = new RequirementsView(root as unknown as HTMLElement, { onEdit: (edit) => sent.push(edit) });
        view.show(editable(), false);

        // Listed Ports first, then Physics: the second row is the mass.
        find(find(root, 'requirement')[1], 'small')[0].fire('click');
        const value = find(root, 'requirements-input').find((input) => input.attributes['aria-label'] === 'Value');
        assert.ok(value);
        assert.strictEqual(value.value, '>0,<=0.05');
        value.value = '>1';
        value.fire('input');
        find(root, 'requirements-button')
            .find((button) => button.textContent === 'Save')
            ?.fire('click');
        assert.deepStrictEqual(sent, [
            { op: 'add', requirement: 'physics', name: 'mass', text: true, replace: true, value: '>1' },
        ]);

        view.editFailed("The requirements would not read: mass: '>heavy'");
        assert.strictEqual(find(root, 'requirements-form').length, 1);
        assert.match(find(root, 'error')[0].textContent, /would not read/);
    });

    test('an object whose requirements are not its own to change says why, and offers nothing', () => {
        const root = new FakeElement('div');
        const view = new RequirementsView(root as unknown as HTMLElement, { onEdit: () => undefined });

        view.show(editable({ editable: "it is an alias of '//pkg:bracket'" }), false);

        assert.deepStrictEqual(find(root, 'requirements-add'), []);
        assert.deepStrictEqual(find(root, 'small'), []);
        assert.match(find(root, 'requirements-note')[0].textContent, /alias of/);
    });

    test('an object that requires nothing yet is where the first requirement is added', () => {
        const root = new FakeElement('div');
        const view = new RequirementsView(root as unknown as HTMLElement, { onEdit: () => undefined });

        view.show(editable({ defined: false, features: [], requirements: [], section: null }), false);

        assert.strictEqual(find(root, 'subtitle')[0].textContent, 'No requirements are declared.');
        assert.strictEqual(find(root, 'requirements-add').length, 1);
    });
});
