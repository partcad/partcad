//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Requirements tab: which mark each requirement gets, how the list is
// grouped, and what each feature says it is validated by.
//
// The verdicts are the daemon's ('partcad.requirements', the code 'pc test -f
// requirements' runs). What is pinned here is that this side draws them as
// they are - a requirement not yet measured is neither green nor red - and that
// every feature offers the LLM, with the tooltip naming the skill.
//

import * as assert from 'assert';

import { RequirementCheck, RequirementsData } from '../../webview/messages';
import {
    LLM_HINT,
    PROBLEMS,
    RequirementsView,
    bannersOf,
    groupChecks,
    markOf,
    summary,
} from '../../webview/requirements';

/** Just enough of an element for 'dom.ts'. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public readonly attributes: Record<string, string> = {};
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

function data(overrides: Partial<RequirementsData> = {}): RequirementsData {
    return {
        object: '//pkg:bracket',
        kind: 'part',
        defined: true,
        verified: true,
        features: [
            { name: 'stands', desc: 'Does not tip over', simulations: ['upright'] },
            { name: 'pretty', desc: 'Looks good', simulations: [] },
        ],
        requirements: [
            check('physics', 'mass', true),
            check('ports', 'top', false),
            check('simulate', 'upright', false),
            check('interfaces', 'm3', true),
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
                [PROBLEMS, ['upright']],
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

    test('the line over the lists says how it stands', () => {
        assert.strictEqual(summary(data(), false), '2 of 4 requirements are met.');
        assert.strictEqual(
            summary(data({ requirements: [check('ports', 'top', true)] }), false),
            'The requirement is met.',
        );
        assert.strictEqual(
            summary(data({ verified: false, requirements: [check('ports', 'top', null)] }), true),
            'Checking the model against what is required…',
        );
        assert.match(summary(data({ requirements: [] }), false), /Nothing here is for PartCAD to measure/);
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
            ],
        );
        const banners = find(root, 'banner');
        assert.deepStrictEqual(
            banners.map((banner) => banner.textContent),
            ['upright', 'LLM', 'LLM'],
        );
        assert.deepStrictEqual(
            find(root, 'llm').map((banner) => banner.title),
            [LLM_HINT, LLM_HINT],
        );
    });

    test('an object with features alone draws no list of checks', () => {
        const root = new FakeElement('div');
        const view = new RequirementsView(root as unknown as HTMLElement);

        view.show(data({ requirements: [] }), false);

        assert.deepStrictEqual(find(root, 'mark'), []);
        assert.strictEqual(find(root, 'requirement-features').length, 1);
    });
});
