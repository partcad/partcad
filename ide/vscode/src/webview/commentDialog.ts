//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The dialog a comment is written in, over the 3D view.
//
// Opened two ways, with "Comments" ticked: by clicking the model - a face or an
// edge of a part, a part of an assembly - which starts a thread about it; and by
// clicking a thread's callout, which answers that thread and shows it whole
// above the box. What a click on a part is about takes the daemon a moment to
// say ('comment.locate'), so the dialog opens at once, saying it is finding
// out, and is told ('setSubject') - Post waits for it.
//
// The text is Markdown and goes into the package as it was typed. Attachments
// are files of the package, which only the host can pick ('onAttach' asks it,
// and 'addAttachments' is its answer). Posting hands the text and the files to
// 'onPost' and waits ('setBusy') for the host to say it was written - the
// dialog then closes - or why not, which it shows and stays open with
// everything still typed.
//
// Escape cancels, as does the backdrop; Ctrl+Enter (Cmd+Enter) posts. None of
// the three cancels while a comment is being written: what the host answers is
// what says whether it was, and a dialog closed under it would leave somebody
// posting it twice. It is a modal dialog for the keyboard too: Tab goes round
// what is in it, and closing it gives the focus back to what had it.
//

import { CommentThread, renderComment } from './comments';
import { el, empty } from './dom';

/** How many dialogs have been made: each heading's id, which names its dialog to a screen reader. */
let made = 0;

/** What the focus can be on inside 'root', in the order Tab takes it there. */
function focusable(root: HTMLElement): HTMLElement[] {
    return Array.from(
        root.querySelectorAll<HTMLElement>('button, textarea, input, select, a[href], [tabindex]:not([tabindex="-1"])'),
    ).filter(
        (element) =>
            !(element as HTMLButtonElement).disabled &&
            !element.hidden &&
            element.closest('[hidden]') === null &&
            element.getClientRects().length > 0,
    );
}

export interface CommentDialogOptions {
    /** What the dialog is for, in its heading: "New comment", "Reply". */
    title: string;
    /** What the comment is about, as far as is known when it opens. */
    subject: string;
    /** Whether that is all there is to know; false keeps Post disabled until 'setSubject' says it is. */
    ready: boolean;
    /** The thread being answered, shown above the box. */
    thread?: CommentThread;
    /** Why nothing can be written here, where nothing can: the box is then read-only. */
    readOnly?: string;
    /** Whether files can be attached: the host knows where the package is. */
    canAttach: boolean;
    onAttach: () => void;
    onPost: (text: string, attachments: string[]) => void;
    onClose: () => void;
}

/** The one dialog of the panel; 'open' replaces whatever it showed. */
export class CommentDialog {
    private readonly backdrop = el('div', 'comment-dialog-backdrop');
    private readonly dialog = el('div', 'comment-dialog');
    private readonly heading = el('div', 'comment-dialog-title');
    private readonly subject = el('div', 'comment-dialog-subject');
    private readonly history = el('div', 'comment-dialog-thread');
    private readonly text = el('textarea', 'comment-dialog-text');
    private readonly files = el('div', 'comment-dialog-files');
    private readonly attach = el('button', 'comment-dialog-attach', 'Attach files…');
    private readonly status = el('div', 'comment-dialog-status');
    private readonly cancel = el('button', 'comment-dialog-cancel', 'Cancel');
    private readonly post = el('button', 'comment-dialog-post', 'Post');
    private options: CommentDialogOptions | undefined;
    private attachments: string[] = [];
    private ready = false;
    private busy = false;
    /** What had the focus before the dialog opened, to have it back once it closes. */
    private opener: HTMLElement | undefined;

    constructor(host: HTMLElement) {
        this.backdrop.hidden = true;
        this.dialog.setAttribute('role', 'dialog');
        this.dialog.setAttribute('aria-modal', 'true');
        made += 1;
        this.heading.id = `comment-dialog-title-${made}`;
        this.dialog.setAttribute('aria-labelledby', this.heading.id);
        this.status.setAttribute('role', 'status');
        this.text.rows = 6;
        this.text.placeholder = 'Write a comment - Markdown: **bold**, *italic*, `code`, - lists, [links](https://…)';
        this.text.setAttribute('aria-label', 'Comment');
        this.attach.title = 'Attach files of the package to the comment';
        this.post.title = 'Write the comment into the package (Ctrl+Enter)';

        const actions = el('div', 'comment-dialog-actions');
        actions.append(this.attach, this.status, this.cancel, this.post);
        this.dialog.append(this.heading, this.subject, this.history, this.text, this.files, actions);
        this.backdrop.appendChild(this.dialog);
        host.appendChild(this.backdrop);

        this.text.addEventListener('input', () => this.update());
        this.attach.addEventListener('click', () => this.options?.onAttach());
        this.cancel.addEventListener('click', () => this.dismiss());
        this.post.addEventListener('click', () => this.submit());
        this.backdrop.addEventListener('mousedown', (event) => {
            if (event.target === this.backdrop) {
                this.dismiss();
            }
        });
        // Escape and Ctrl+Enter wherever the focus is while the dialog is up -
        // posting disables the box, and the focus leaves it - and before
        // anything else sees them.
        document.addEventListener(
            'keydown',
            (event: KeyboardEvent) => {
                if (this.backdrop.hidden) {
                    return;
                }
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    this.dismiss();
                } else if (event.key === 'Tab') {
                    // Round what is in the dialog, as a modal dialog keeps it.
                    const inside = focusable(this.dialog);
                    if (inside.length === 0) {
                        event.preventDefault();
                        return;
                    }
                    const at = inside.indexOf(document.activeElement as HTMLElement);
                    const next = event.shiftKey
                        ? at <= 0
                            ? inside.length - 1
                            : at - 1
                        : at === -1 || at === inside.length - 1
                          ? 0
                          : at + 1;
                    event.preventDefault();
                    event.stopPropagation();
                    inside[next].focus();
                } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    event.stopPropagation();
                    this.submit();
                }
            },
            true,
        );
        // Kept from the 3D view underneath: its keys orbit the camera, and a key
        // typed into a comment is a key typed into a comment.
        this.dialog.addEventListener('keydown', (event: KeyboardEvent) => event.stopPropagation());
        this.dialog.addEventListener('wheel', (event) => event.stopPropagation());
    }

    /** Whether the dialog is up. */
    public get isOpen(): boolean {
        return !this.backdrop.hidden;
    }

    public open(options: CommentDialogOptions): void {
        if (this.backdrop.hidden) {
            const active = document.activeElement;
            this.opener = active instanceof HTMLElement && active !== document.body ? active : undefined;
        }
        this.options = options;
        this.attachments = [];
        this.busy = false;
        this.heading.textContent = options.title;
        empty(this.history);
        if (options.thread !== undefined) {
            for (const comment of options.thread.comments) {
                this.history.appendChild(renderComment(comment));
            }
        }
        this.history.hidden = options.thread === undefined;
        this.text.value = '';
        this.text.disabled = options.readOnly !== undefined;
        this.attach.hidden = !options.canAttach || options.readOnly !== undefined;
        this.post.hidden = options.readOnly !== undefined;
        this.drawFiles();
        this.setSubject(options.subject, options.ready);
        this.setStatus(options.readOnly ?? '');
        this.backdrop.hidden = false;
        if (options.readOnly === undefined) {
            this.text.focus();
        } else {
            this.cancel.focus();
        }
        if (options.thread !== undefined) {
            this.history.scrollTop = this.history.scrollHeight;
        }
    }

    /** Say what the comment is about, and whether that is settled. */
    public setSubject(text: string, ready: boolean): void {
        this.subject.textContent = text;
        this.ready = ready;
        this.update();
    }

    /** A line beside the buttons: what is going on, or what went wrong. */
    public setStatus(text: string, failure = false): void {
        this.status.textContent = text;
        this.status.classList.toggle('failure', failure);
    }

    /** Waiting for the host to write it, or not any more - when the box has the focus back, to go on typing. */
    public setBusy(busy: boolean): void {
        this.busy = busy;
        this.text.disabled = busy || this.options?.readOnly !== undefined;
        this.update();
        if (!busy && !this.text.disabled && !this.backdrop.hidden) {
            this.text.focus();
        }
    }

    /** Whether files can be attached: once the host has said where the package is. */
    public setCanAttach(canAttach: boolean): void {
        this.attach.hidden = !canAttach || this.options?.readOnly !== undefined;
    }

    /** Files the host picked, relative to the package; each once. */
    public addAttachments(files: readonly string[]): void {
        for (const file of files) {
            if (!this.attachments.includes(file)) {
                this.attachments.push(file);
            }
        }
        this.drawFiles();
    }

    /** Close it, whatever it was doing: what the host does once it has answered, or once there is another object. */
    public close(): void {
        if (this.backdrop.hidden) {
            return;
        }
        this.backdrop.hidden = true;
        const options = this.options;
        this.options = undefined;
        this.busy = false;
        const opener = this.opener;
        this.opener = undefined;
        if (opener?.isConnected) {
            opener.focus();
        }
        options?.onClose();
    }

    /** Escape, Cancel or the backdrop: close it, unless what is posted is still being written. */
    private dismiss(): void {
        if (this.busy) {
            this.setStatus('Still writing it into partcad.yaml - it closes once that is done, or says why not.');
            return;
        }
        this.close();
    }

    private submit(): void {
        if (this.post.disabled || this.post.hidden || this.options === undefined) {
            return;
        }
        this.options.onPost(this.text.value, [...this.attachments]);
    }

    private update(): void {
        this.post.disabled = this.busy || !this.ready || this.text.value.trim() === '';
        this.attach.disabled = this.busy;
        this.cancel.disabled = this.busy;
    }

    private drawFiles(): void {
        empty(this.files);
        this.files.hidden = this.attachments.length === 0;
        this.attachments.forEach((file, index) => {
            const chip = el('span', 'comment-dialog-file', file);
            const remove = el('button', 'comment-dialog-file-remove', '×');
            remove.title = `Do not attach ${file}`;
            remove.setAttribute('aria-label', `Do not attach ${file}`);
            remove.addEventListener('click', () => {
                this.attachments.splice(index, 1);
                this.drawFiles();
            });
            chip.appendChild(remove);
            this.files.appendChild(chip);
        });
    }
}
