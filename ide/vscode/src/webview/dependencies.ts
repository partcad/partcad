//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What something depends on: the Operations group's Dependencies tab, and the
// "Dependencies at it" view under a revision on the Revisions tab
// ('ops.deps.list').
//
// A package depends on what it declares - each dependency with what the
// declaration says (its location, the branch it tracks, the commit it is
// pinned to) and the commit it is at - and the tab is where that is changed:
// a dependency declared ('ops.deps.add'), removed ('ops.deps.remove'), or its
// pin moved to the tip of the branch it tracks ('ops.deps.update'), each
// written into the package's 'partcad.yaml' by the daemon, which this tab then
// asks again. Below that, in sections of their own, what the package's objects
// reach without declaring it - which the form can be filled in from - and the
// packages in directories below it, which need no pin.
//
// An object depends on the objects it names, or once built places: each with
// how and how many times, and the commit the package it comes from is at. A
// row shows that object in the panel, and a package opens in the Package
// Explorer - at the commit it is at, too.
//

import { el, empty, placeholder } from './dom';
import {
    DeclaredDependency,
    DepsData,
    ObjectDependency,
    ObjectDepsData,
    OpsParams,
    OpsWriteMethod,
    PackageDepsData,
    UndeclaredDependency,
} from './messages';
import {
    Answer,
    OpsCallbacks,
    OpsSubject,
    button,
    capitalized,
    chips,
    focusSection,
    grid,
    isPackage,
    objectCell,
    packageButton,
    sameSubject,
    section,
    shortRevision,
    thisSubject,
} from './operations';

/** Whether an answer is about a package, rather than about one object. */
export function isPackageDeps(data: DepsData): data is PackageDepsData {
    return Array.isArray((data as PackageDepsData).declared);
}

/** What a dependency's commit cell says when it has none to open. */
function withoutCommit(row: DeclaredDependency): string {
    if (row.sha === null && row.type !== 'git') {
        return 'not in a repository';
    }
    return 'not known';
}

/** What a row of the table does beyond naming a dependency: Update and Remove, on the tab and not at a revision. */
export interface DependencyActions {
    update: (row: DeclaredDependency) => void;
    remove: (row: DeclaredDependency) => void;
    /** The dependency whose Remove was pressed and waits to be confirmed, if any. */
    removing?: string;
    confirm: (row: DeclaredDependency) => void;
    cancel: () => void;
    /** A change in flight: every action waits for it. */
    busy: boolean;
}

/**
 * The dependencies a package declares: the name it declares each under (opening
 * it in the Package Explorer), its type, location, the branch it tracks, the
 * revision it is pinned to, and the commit it is at (opening it there at that
 * commit) - with Update and Remove where 'actions' says.
 */
export function declaredTable(
    rows: DeclaredDependency[],
    callbacks: Pick<OpsCallbacks, 'openPackage'>,
    actions?: DependencyActions,
): HTMLElement {
    const columns = ['Name', 'Type', 'Location', 'Branch', 'Pinned', 'At'];
    const { table, body } = grid(actions ? [...columns, ''] : columns, 'deps-declared');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'deps-dependency'));
        tr.dataset.name = row.name;
        const target = row.current ?? row.package;
        tr.appendChild(el('td')).appendChild(packageButton(row.name, target, callbacks, 'deps-name'));
        tr.appendChild(el('td', undefined, row.type ?? ''));
        tr.appendChild(el('td', 'deps-location', row.location ?? ''));
        tr.appendChild(el('td', 'name', row.track ?? ''));
        tr.appendChild(el('td', 'name deps-pinned', shortRevision(row.pinned)));
        const at = tr.appendChild(el('td'));
        if (row.short && row.versioned) {
            at.appendChild(
                packageButton(
                    row.short,
                    row.versioned,
                    callbacks,
                    'deps-sha name',
                    `Open ${row.versioned} - the dependency at this commit - in the Package Explorer`,
                ),
            );
        } else {
            at.appendChild(el('span', 'placeholder', withoutCommit(row)));
        }
        if (actions) {
            tr.appendChild(actionsCell(row, actions));
        }
    }
    return table;
}

function actionsCell(row: DeclaredDependency, actions: DependencyActions): HTMLElement {
    const cell = el('td', 'actions');
    if (actions.removing === row.name) {
        const yes = cell.appendChild(
            button(`Remove ${row.name}`, 'small deps-confirm', `Take ${row.name} out of partcad.yaml`, () =>
                actions.confirm(row),
            ),
        );
        yes.disabled = actions.busy;
        cell.appendChild(button('Cancel', 'small secondary', 'Change nothing', () => actions.cancel()));
        return cell;
    }
    const update = cell.appendChild(
        button(
            'Update',
            'small deps-update',
            row.track
                ? `Pin ${row.name} to the tip of ${row.track}, and fetch it again (pc ops deps update)`
                : `${row.name} tracks no branch, so there is nothing to move its pin to`,
            () => actions.update(row),
        ),
    );
    update.disabled = actions.busy || !row.track;
    const remove = cell.appendChild(
        button(
            'Remove',
            'small secondary deps-remove',
            `Take ${row.name} out of partcad.yaml (pc ops deps remove)`,
            () => actions.remove(row),
        ),
    );
    remove.disabled = actions.busy;
    return cell;
}

/**
 * The packages the package's objects reach without declaring them, each with
 * the objects that do - and, on the tab, a Declare that fills the form in,
 * which waits for a change in flight ('busy') rather than replace the form it
 * may have sent.
 */
export function undeclaredTable(
    rows: UndeclaredDependency[],
    callbacks: Pick<OpsCallbacks, 'openPackage' | 'showObject'>,
    declare?: (row: UndeclaredDependency) => void,
    busy = false,
): HTMLElement {
    const { table, body } = grid(declare ? ['Package', 'Used by', ''] : ['Package', 'Used by'], 'deps-undeclared');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'deps-undeclared-row'));
        tr.appendChild(el('td')).appendChild(packageButton(row.package, row.package, callbacks));
        const users = tr.appendChild(el('td', 'deps-users'));
        for (const user of row.users) {
            const line = users.appendChild(el('div'));
            // The users are objects of this package, whose kind the answer does
            // not say: named, with how many times each, rather than opened.
            line.appendChild(el('span', 'name', user.object));
            if (user.count > 1) {
                line.appendChild(el('span', 'placeholder', ` ×${user.count}`));
            }
        }
        if (declare) {
            const cell = tr.appendChild(el('td', 'actions'));
            const declaring = cell.appendChild(
                button('Declare…', 'small secondary deps-declare', `Declare ${row.package} as a dependency`, () =>
                    declare(row),
                ),
            );
            declaring.disabled = busy;
        }
    }
    return table;
}

/** The packages in directories below a package: they need no pin, the commit checked out being theirs. */
export function subpackagesTable(
    rows: { name: string; package: string }[],
    callbacks: Pick<OpsCallbacks, 'openPackage'>,
): HTMLElement {
    const { table, body } = grid(['Name', 'Package'], 'deps-subpackages');
    for (const row of rows) {
        const tr = body.appendChild(el('tr'));
        tr.appendChild(el('td', 'name', row.name));
        tr.appendChild(el('td')).appendChild(packageButton(row.package, row.package, callbacks));
    }
    return table;
}

/**
 * The objects an object names: each object (shown in the panel), its kind, how
 * and how many times, and the package it comes from with the commit that is at.
 */
export function objectDependenciesTable(
    rows: ObjectDependency[],
    callbacks: Pick<OpsCallbacks, 'openPackage' | 'showObject'>,
): HTMLElement {
    const { table, body } = grid(['Object', 'Kind', 'How', 'Uses', 'From'], 'deps-objects');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'deps-object'));
        tr.appendChild(objectCell(row, callbacks));
        tr.appendChild(el('td', undefined, row.kind ?? ''));
        tr.appendChild(el('td')).appendChild(chips(row.how));
        tr.appendChild(el('td', 'numeric', String(row.count)));
        const from = tr.appendChild(el('td', 'deps-from'));
        from.appendChild(packageButton(row.package, row.package, callbacks));
        if (row.revision && row.short) {
            from.appendChild(
                packageButton(
                    row.short,
                    // A package named at a revision is loaded under that name,
                    // which is the commit this is already: it takes no second.
                    row.package.includes('@') ? row.package : `${row.package}@${row.revision}`,
                    callbacks,
                    'deps-sha name',
                    `Open ${row.package} at ${row.short} - the commit it is at - in the Package Explorer`,
                ),
            );
        }
    }
    return table;
}

/**
 * What something depends on, into 'host', with nothing to change: the Revisions
 * tab's "Dependencies at it" view.
 */
export function renderDependencies(
    host: HTMLElement,
    data: DepsData,
    callbacks: Pick<OpsCallbacks, 'openPackage' | 'showObject'>,
    what: string,
): void {
    empty(host);
    if (!isPackageDeps(data)) {
        const rows = (data as ObjectDepsData).dependencies ?? [];
        host.appendChild(
            rows.length > 0 ? objectDependenciesTable(rows, callbacks) : placeholder(`${what} uses nothing.`),
        );
        return;
    }
    const declared = data.declared ?? [];
    host.appendChild(
        declared.length > 0 ? declaredTable(declared, callbacks) : placeholder(`${what} declares no dependencies.`),
    );
    const undeclared = data.undeclared ?? [];
    if (undeclared.length > 0) {
        host.appendChild(el('p', 'ops-subtitle', 'Used, not declared'));
        host.appendChild(undeclaredTable(undeclared, callbacks));
    }
    const subpackages = data.subpackages ?? [];
    if (subpackages.length > 0) {
        host.appendChild(
            el(
                'p',
                'placeholder deps-subpackages-line',
                `Sub-packages: ${subpackages.map((row) => row.name).join(', ')}`,
            ),
        );
    }
}

/** The Add dependency form, as typed so far. */
interface AddForm {
    name: string;
    location: string;
    track: string;
}

/** The Dependencies tab: what the package, or the object, on screen depends on. */
export class DependenciesView {
    private subject: OpsSubject | undefined;
    private answer: Answer<DepsData> | undefined;
    /** What the last change did, or why it did nothing. */
    private note: { text: string; error: boolean } | undefined;
    private form: AddForm | undefined;
    /** The dependency whose Remove waits to be confirmed. */
    private removing: string | undefined;
    /**
     * The changes in flight, each with the object it was asked on - one per
     * object at most, and as many objects as the tab was moved between. Kept
     * when the tab starts over - shown again, after a save, say - so that the
     * tab started over on an object waits for its change as well, rather than
     * send another whose answer this one's would be taken for.
     */
    private readonly pending = new Set<{ subject: OpsSubject }>();
    /** The sections folded away, by id: the sub-packages, until opened, since a root package can have dozens. */
    private readonly folded = new Set<string>(['subpackages']);

    constructor(
        private readonly pane: HTMLElement,
        private readonly callbacks: OpsCallbacks,
    ) {
        this.pane.classList.add('deps');
    }

    /** Forget the last object, and say 'text' where the tab goes. */
    public setBusy(text: string): void {
        this.subject = undefined;
        this.answer = undefined;
        this.note = undefined;
        this.form = undefined;
        this.removing = undefined;
        empty(this.pane);
        this.pane.appendChild(placeholder(text));
    }

    /** Whether a change is in flight for the object on screen: every action waits for it. */
    private get busy(): boolean {
        return [...this.pending].some((change) => sameSubject(change.subject, this.subject));
    }

    /** The tab has been opened on 'subject': ask what it depends on. */
    public start(subject: OpsSubject): void {
        this.subject = subject;
        this.ask();
    }

    private ask(): void {
        const subject = this.subject;
        if (subject === undefined) {
            return;
        }
        this.answer = 'pending';
        this.draw();
        this.callbacks.ask({ method: 'ops.deps.list' }, (data, error) => {
            if (this.subject !== subject) {
                return;
            }
            this.answer =
                error !== undefined
                    ? { error }
                    : data
                      ? { data: data as DepsData }
                      : { error: 'PartCAD had nothing to say about what this depends on.' };
            this.draw();
        });
    }

    /**
     * Change something, say what came of it, and ask again: what the package
     * declares is what the daemon says now - after a failure too, which may
     * have come after some of it was written (an update pins one dependency
     * after another). 'form' is the Add form that sent it, the one draft a
     * success takes away: Update all leaves a draft as it is.
     */
    private change(method: OpsWriteMethod, params: OpsParams, done: (data: unknown) => string, form?: AddForm): void {
        const subject = this.subject;
        if (subject === undefined || this.busy) {
            return;
        }
        const mine = { subject };
        this.pending.add(mine);
        this.note = undefined;
        this.draw();
        this.callbacks.write({ method, whole: true, params }, ({ data, error }) => {
            // This change is answered; another object's goes on being waited for.
            this.pending.delete(mine);
            if (!sameSubject(this.subject, subject)) {
                return;
            }
            this.removing = undefined;
            if (error !== undefined) {
                // Said over the list asked again, which keeps it.
                this.note = { text: error, error: true };
                this.ask();
                return;
            }
            this.note = { text: done(data), error: false };
            if (form !== undefined && this.form === form) {
                this.form = undefined;
            }
            this.ask();
        });
    }

    private draw(): void {
        empty(this.pane);
        const answer = this.answer;
        const what = thisSubject(this.subject);
        if (answer === undefined || answer === 'pending') {
            this.pane.appendChild(placeholder(`Asking PartCAD what ${what} depends on…`));
            if (this.note) {
                this.pane.appendChild(this.noteLine());
            }
            return;
        }
        if ('error' in answer) {
            this.pane.appendChild(el('p', 'error', answer.error));
            return;
        }
        const data = answer.data;
        if (!isPackageDeps(data)) {
            const rows = data.dependencies ?? [];
            this.pane.appendChild(
                rows.length > 0
                    ? objectDependenciesTable(rows, this.callbacks)
                    : placeholder(`${capitalized(what)} names no other object.`),
            );
            return;
        }
        if (isPackage(this.subject)) {
            this.pane.appendChild(this.toolbar());
        }
        if (this.note) {
            this.pane.appendChild(this.noteLine());
        }
        if (this.form) {
            this.pane.appendChild(this.addForm(this.form));
        }
        const declared = data.declared ?? [];
        this.pane.appendChild(
            declared.length > 0
                ? declaredTable(declared, this.callbacks, {
                      update: (row) =>
                          this.change('ops.deps.update', { names: [row.name] }, (done) => updated(done, row.name)),
                      remove: (row) => {
                          this.removing = row.name;
                          this.draw();
                      },
                      removing: this.removing,
                      confirm: (row) =>
                          this.change('ops.deps.remove', { name: row.name }, (done) => removed(done, row.name)),
                      cancel: () => {
                          this.removing = undefined;
                          this.draw();
                      },
                      busy: this.busy,
                  })
                : placeholder(`${capitalized(what)} declares no dependencies.`),
        );
        const undeclared = data.undeclared ?? [];
        this.pane.appendChild(
            this.section('undeclared', `Used, not declared (${undeclared.length})`, (body) =>
                body.appendChild(
                    undeclared.length > 0
                        ? undeclaredTable(undeclared, this.callbacks, (row) => this.declare(row), this.busy)
                        : placeholder('Every package its objects use is declared, or is one of its own.'),
                ),
            ),
        );
        const subpackages = data.subpackages ?? [];
        this.pane.appendChild(
            this.section('subpackages', `Sub-packages (${subpackages.length})`, (body) =>
                body.appendChild(
                    subpackages.length > 0
                        ? subpackagesTable(subpackages, this.callbacks)
                        : placeholder('No package is in a directory below it.'),
                ),
            ),
        );
    }

    private toolbar(): HTMLElement {
        const bar = el('div', 'requirements-buttons deps-toolbar');
        const add = bar.appendChild(
            button('Add dependency…', 'deps-add', 'Declare a package this one depends on (pc ops deps add)', () => {
                this.form = this.form ?? { name: '', location: '', track: '' };
                this.draw();
            }),
        );
        add.disabled = this.busy;
        const update = bar.appendChild(
            button(
                'Update all',
                'secondary deps-update-all',
                'Pin every dependency that tracks a branch to its tip, and fetch them again (pc ops deps update)',
                () => this.change('ops.deps.update', {}, (done) => updated(done)),
            ),
        );
        update.disabled = this.busy;
        if (this.busy) {
            bar.appendChild(el('span', 'placeholder', 'Changing the declaration…'));
        }
        return bar;
    }

    private noteLine(): HTMLElement {
        const note = this.note as { text: string; error: boolean };
        return el('p', `requirements-note${note.error ? ' error' : ''}`, note.text);
    }

    /** "Declare…" on a package used but not declared: the form, with what can be told of it filled in. */
    private declare(row: UndeclaredDependency): void {
        if (this.busy) {
            return;
        }
        const name = row.package.split('/').filter(Boolean).pop() ?? '';
        this.form = { name, location: '', track: '' };
        this.note = undefined;
        this.draw();
    }

    private addForm(form: AddForm): HTMLElement {
        const box = el('div', 'requirements-form deps-form');
        box.appendChild(el('h3', undefined, 'Add a dependency'));
        const fields = box.appendChild(el('div', 'requirements-fields'));
        const field = (label: string, key: keyof AddForm, hint: string) => {
            const row = fields.appendChild(el('label', 'requirements-field'));
            row.appendChild(el('span', 'requirements-field-label', label));
            const input = row.appendChild(el('input', 'requirements-input')) as HTMLInputElement;
            input.type = 'text';
            input.spellcheck = false;
            input.value = form[key];
            input.placeholder = hint;
            input.dataset.field = key;
            input.disabled = this.busy;
            input.setAttribute('aria-label', label);
            input.addEventListener('input', () => (form[key] = input.value));
            input.addEventListener('change', () => (form[key] = input.value));
        };
        field('Name', 'name', 'what the package calls it: std');
        field('Location', 'location', 'a path, a git URL or a tarball URL');
        field('Branch (optional)', 'track', 'for git: the branch whose tip it is pinned to');
        const buttons = box.appendChild(el('div', 'requirements-buttons'));
        const add = buttons.appendChild(
            button('Add', 'deps-add-confirm', "Write it into the package's partcad.yaml", () => {
                const name = form.name.trim();
                const location = form.location.trim();
                if (!name || !location) {
                    this.note = { text: 'A dependency needs a name and a location.', error: true };
                    this.draw();
                    return;
                }
                const track = form.track.trim();
                this.change(
                    'ops.deps.add',
                    { name, location, track: track || undefined },
                    () => `Declared ${name}.`,
                    form,
                );
            }),
        );
        add.disabled = this.busy;
        buttons.appendChild(
            button('Cancel', 'secondary', 'Change nothing', () => {
                this.form = undefined;
                this.draw();
            }),
        );
        return box;
    }

    private section(id: string, title: string, fill: (body: HTMLElement) => void): HTMLElement {
        return section(
            id,
            title,
            !this.folded.has(id),
            (which) => {
                if (!this.folded.delete(which)) {
                    this.folded.add(which);
                }
                this.draw();
                focusSection(this.pane, which);
            },
            fill,
        );
    }
}

/** What 'ops.deps.update' did, in a sentence. */
export function updated(data: unknown, name?: string): string {
    const stats = (data ?? {}) as { pinned?: number; current?: number; failed?: number };
    const parts: string[] = [];
    if (stats.pinned) {
        parts.push(`pinned ${stats.pinned} to the tip of ${stats.pinned === 1 ? 'its' : 'their'} branch`);
    }
    if (stats.current) {
        parts.push(`${stats.current} ${stats.current === 1 ? 'was' : 'were'} there already`);
    }
    if (stats.failed) {
        parts.push(`${stats.failed} failed (see PartCAD's log)`);
    }
    if (parts.length === 0) {
        return `${name ?? 'The tracked dependencies'}: nothing to update.`;
    }
    return name !== undefined ? `Updated ${name}: ${parts.join('; ')}.` : `${capitalized(parts.join('; '))}.`;
}

/** What 'ops.deps.remove' did, in a sentence: and what still uses it, which will not load until it uses something else. */
export function removed(data: unknown, name: string): string {
    const users = ((data ?? {}) as { users?: string[] }).users ?? [];
    if (users.length === 0) {
        return `Removed ${name}.`;
    }
    return `Removed ${name}. Still used by ${users.join(', ')}, which will not load until they use something else.`;
}
