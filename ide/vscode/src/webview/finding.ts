//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What a topology finding says, over the 3D view it is shown in.
//
// "Show" on the Topology tab takes the reader to the 3D view, where the finding
// is drawn - the faces nothing tolerances, the volume two parts share - with
// the rest of the object faded. What the check said about it stays on the tab
// the reader just left. So it comes along: this card, in the top-left corner of
// the view, says which check it is and how it came out, every line the check
// said, and what is drawn, and has the way back to the tab.
//
// Chosen over the alternatives for what each of them loses:
//
// - the one-line chip the CMF tab uses: room for a title and nothing else, and
//   the words are the finding ("5 of its 7 faces have no tolerance: the largest
//   is face 3, a Plane of 200 mm^2");
// - a tooltip on the drawn geometry: found only by hovering, and a face drawn
//   behind another cannot be hovered;
// - a 3D view on the Topology tab itself: a second WebGL view of the same model,
//   and a smaller one, beside a tab that already has a page of text;
// - a picture rendered into the tab: cannot be turned, which is the point of
//   showing a place on a solid.
//
// The card is the words; the callouts the scene pins to the pieces ('scene.ts',
// 'setFindingCallouts') are the place. It folds to its title line, out of the
// way of the model, and closing it shows all of the object again.
//

import { el, empty } from './dom';
import { Finding, MARK_TEXT, MARK_TITLE, VERDICT, commandOf, findings, markOf } from './test';

export interface FindingCallbacks {
    /** The reader closed the card: show all of the object again. */
    onClose: () => void;
    /** "Back": the object the finding is on, on its Topology tab, with this check open. */
    onBack: (finding: Finding) => void;
}

export class FindingCard {
    private readonly root = el('section', 'finding-card');
    private readonly head = el('div', 'finding-head');
    private readonly mark = el('span', 'finding-mark');
    private readonly title = el('span', 'finding-title');
    private readonly fold = el('button', 'finding-fold');
    private readonly close = el('button', 'finding-close', '×');
    private readonly body = el('div', 'finding-body');
    private shown: Finding | undefined;

    constructor(
        host: HTMLElement,
        private readonly callbacks: FindingCallbacks,
    ) {
        this.root.hidden = true;
        this.root.setAttribute('role', 'region');
        this.root.setAttribute('aria-label', 'Topology finding');
        for (const button of [this.fold, this.close]) {
            button.type = 'button';
        }
        this.close.title = 'Show all of it again';
        this.close.setAttribute('aria-label', 'Show all of it again');
        this.close.addEventListener('click', () => this.callbacks.onClose());
        this.fold.addEventListener('click', () => this.setFolded(!this.root.classList.contains('folded')));
        this.head.append(this.mark, this.title, this.fold, this.close);
        this.root.append(this.head, this.body);
        host.appendChild(this.root);
        this.setFolded(false);
    }

    /** The finding on screen, if any. */
    public get finding(): Finding | undefined {
        return this.shown;
    }

    /** Say this finding over the view, unfolded. */
    public show(finding: Finding): void {
        this.shown = finding;
        const mark = markOf(
            { name: finding.check, status: finding.status, findings: [], artifacts: [], doc: null },
            false,
        );
        this.mark.className = `finding-mark ${mark}`;
        this.mark.textContent = MARK_TEXT[mark];
        this.mark.title = MARK_TITLE[mark];
        this.mark.setAttribute('aria-label', MARK_TITLE[mark]);
        this.title.textContent = finding.title;
        this.title.title = finding.title;

        empty(this.body);
        const about = el('p', 'finding-about');
        if (finding.subject !== undefined) {
            about.append('On ', el('code', undefined, finding.subject.name), ' · ');
        }
        about.append(el('code', undefined, commandOf(finding.subtype, finding.check)));
        this.body.appendChild(about);
        if (finding.status !== null && finding.status !== undefined) {
            this.body.appendChild(el('p', 'finding-status', VERDICT[finding.status]));
        }
        if (finding.findings.length > 0) {
            this.body.appendChild(findings(finding.findings));
        }
        const drawn = el('p', 'finding-drawn');
        drawn.append(el('strong', undefined, finding.focus.label));
        if (finding.desc) {
            drawn.append(': ', finding.desc);
        }
        this.body.appendChild(drawn);
        if (finding.features.length > 0) {
            this.body.appendChild(
                el(
                    'p',
                    'finding-note',
                    finding.features.length === 1
                        ? 'A callout marks where it is.'
                        : `Callouts mark ${finding.features.length} of the pieces.`,
                ),
            );
        }
        if (finding.subject !== undefined) {
            const back = el('button', 'finding-back', 'Back to the Topology tab');
            back.type = 'button';
            back.title = `${finding.subject.package}:${finding.subject.name}, with '${finding.check}' open`;
            back.addEventListener('click', () => {
                if (this.shown !== undefined) {
                    this.callbacks.onBack(this.shown);
                }
            });
            this.body.appendChild(back);
        }
        this.setFolded(false);
        this.root.hidden = false;
    }

    /** Take the card away. */
    public hide(): void {
        this.shown = undefined;
        this.root.hidden = true;
        empty(this.body);
    }

    private setFolded(folded: boolean): void {
        this.root.classList.toggle('folded', folded);
        this.body.hidden = folded;
        this.fold.textContent = folded ? '▸' : '▾';
        const label = folded ? 'Show what the check said' : 'Fold to the title';
        this.fold.title = label;
        this.fold.setAttribute('aria-label', label);
        this.fold.setAttribute('aria-expanded', String(!folded));
    }
}
