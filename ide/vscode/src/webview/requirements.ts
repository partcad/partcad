//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Requirements" tab.
//
// What an object was required to be, and how far the model is it. Two halves,
// because a requirement is one of two kinds of thing:
//
//   - what PartCAD can measure - the ports, the interfaces and the physical
//     properties - listed with a mark beside each: green where 'pc test' finds
//     the model meets it, red where it does not;
//   - the features, which are prose, in a table: what each is, and what it is
//     validated by - the 'simulate:' entries that name it, and an LLM reading
//     the evidence through the '/pc:validate' skill.
//
// None of it is worked out here. The daemon's 'requirements.check' answers with
// what 'partcad.requirements' decided, which is the code 'pc test -f
// requirements' runs; this file only draws the answer.
//

import { el, empty, placeholder } from './dom';
import { RequirementCheck, RequirementFeature, RequirementsData } from './messages';

/**
 * What the "LLM" banner says when pointed at.
 *
 * Cursor's spelling of the skill rather than Claude Code's ('/pc:validate'),
 * because it is the one both editors' users can read as a name: the IDE does not
 * know which agent is open beside it.
 */
export const LLM_HINT = 'Validate using /pc-validate';

/** The sections PartCAD measures, in the order they are listed, and their headings. */
export const SECTIONS: [string, string][] = [
    ['ports', 'Ports'],
    ['interfaces', 'Interfaces'],
    ['physics', 'Physics'],
];

/** Where a check of any other section - a requirement that could not be read, a dangling 'feature:' - is listed. */
export const PROBLEMS = 'Problems';

export type Mark = 'pass' | 'fail' | 'pending';

/**
 * What a check's mark is.
 *
 * 'pending' while the verdicts are not in - a requirement nobody has measured
 * yet is neither met nor unmet, and drawing it red or green would say it is.
 */
export function markOf(check: RequirementCheck): Mark {
    if (check.passed === true) {
        return 'pass';
    }
    if (check.passed === false) {
        return 'fail';
    }
    return 'pending';
}

/** The checks, by the heading they are listed under: the measured sections first, then everything else. */
export function groupChecks(checks: RequirementCheck[]): { heading: string; checks: RequirementCheck[] }[] {
    const groups: { heading: string; checks: RequirementCheck[] }[] = [];
    for (const [section, heading] of SECTIONS) {
        const inSection = checks.filter((check) => check.section === section);
        if (inSection.length > 0) {
            groups.push({ heading, checks: inSection });
        }
    }
    const known = new Set(SECTIONS.map(([section]) => section));
    const others = checks.filter((check) => !known.has(check.section));
    if (others.length > 0) {
        groups.push({ heading: PROBLEMS, checks: others });
    }
    return groups;
}

export interface Banner {
    label: string;
    title: string;
    kind: 'simulation' | 'llm';
}

/**
 * What a feature is validated by: each simulation that names it, then the LLM.
 *
 * The LLM banner is on every feature, the ones a simulation stands behind
 * included: a simulation demonstrates the claim it was written for, and whether
 * that is the whole of the feature is a judgement it cannot make.
 */
export function bannersOf(feature: RequirementFeature): Banner[] {
    const banners: Banner[] = (feature.simulations ?? []).map((name) => ({
        label: name,
        title: `Demonstrated by the simulation '${name}' (pc sim)`,
        kind: 'simulation',
    }));
    banners.push({ label: 'LLM', title: LLM_HINT, kind: 'llm' });
    return banners;
}

/** One line saying how it stands, over the lists. */
export function summary(data: RequirementsData, checking: boolean): string {
    const measured = data.requirements;
    if (measured.length === 0) {
        return data.features.length > 0
            ? 'Nothing here is for PartCAD to measure: every feature is validated by a simulation or by reading the evidence.'
            : 'No requirements are declared.';
    }
    if (!data.verified) {
        return checking ? 'Checking the model against what is required…' : 'Not checked yet.';
    }
    const failed = measured.filter((check) => check.passed === false).length;
    if (failed === 0) {
        return measured.length === 1 ? 'The requirement is met.' : `All ${measured.length} requirements are met.`;
    }
    return `${measured.length - failed} of ${measured.length} requirements are met.`;
}

const MARK_TEXT: Record<Mark, string> = { pass: '✓', fail: '✗', pending: '…' };
const MARK_TITLE: Record<Mark, string> = {
    pass: 'Met (pc test)',
    fail: 'Not met (pc test)',
    pending: 'Not checked yet',
};

export class RequirementsView {
    constructor(private readonly root: HTMLElement) {}

    public setBusy(text: string): void {
        this.reset();
        this.root.appendChild(placeholder(text));
    }

    public showError(text: string): void {
        this.reset();
        this.root.appendChild(el('p', 'error', text));
    }

    /** Draw what is required, and the verdicts where they are in; 'checking' says they are on the way. */
    public show(data: RequirementsData, checking: boolean): void {
        this.reset();
        this.root.classList.add('sheet', 'requirements');
        this.root.appendChild(el('p', 'subtitle', summary(data, checking)));

        for (const group of groupChecks(data.requirements)) {
            this.root.appendChild(el('h2', undefined, group.heading));
            this.root.appendChild(this.checkTable(group.checks));
        }

        if (data.features.length > 0) {
            this.root.appendChild(el('h2', undefined, 'Features'));
            this.root.appendChild(this.featureTable(data.features));
        }
    }

    private reset(): void {
        empty(this.root);
        this.root.className = 'pane';
    }

    private checkTable(checks: RequirementCheck[]): HTMLElement {
        const table = el('table', 'grid requirement-checks');
        const head = el('tr');
        for (const column of ['', 'Name', 'Required', 'Found']) {
            head.appendChild(el('th', undefined, column));
        }
        table.appendChild(el('thead')).appendChild(head);

        const body = el('tbody');
        for (const check of checks) {
            const mark = markOf(check);
            const row = el('tr', `requirement ${mark}`);
            const cell = el('td', `mark ${mark}`, MARK_TEXT[mark]);
            cell.title = MARK_TITLE[mark];
            cell.setAttribute('aria-label', MARK_TITLE[mark]);
            row.appendChild(cell);
            row.appendChild(el('td', 'name', check.name));
            row.appendChild(el('td', undefined, check.requirement));
            row.appendChild(el('td', 'detail', check.detail ?? ''));
            body.appendChild(row);
        }
        table.appendChild(body);
        return table;
    }

    private featureTable(features: RequirementFeature[]): HTMLElement {
        const table = el('table', 'grid requirement-features');
        const head = el('tr');
        for (const column of ['Feature', 'Description', 'Validated by']) {
            head.appendChild(el('th', undefined, column));
        }
        table.appendChild(el('thead')).appendChild(head);

        const body = el('tbody');
        for (const feature of features) {
            const row = el('tr');
            row.appendChild(el('td', 'name', feature.name));
            row.appendChild(el('td', 'description', feature.desc));
            const validators = el('td', 'validators');
            for (const banner of bannersOf(feature)) {
                const node = el('span', `banner ${banner.kind}`, banner.label);
                node.title = banner.title;
                validators.appendChild(node);
            }
            row.appendChild(validators);
            body.appendChild(row);
        }
        table.appendChild(body);
        return table;
    }
}
