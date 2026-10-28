//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The view panel's orientation gizmo: the three axes of the object's frame, as
// they lie from where the view is looked at from.
//
// Each axis is a line from the middle to a ball at its positive end, with a
// smaller ball at its negative end, coloured as a port's triad is - X red, Y
// green, Z blue - and drawn farthest first, so that the ones pointing at the
// reader are on top. Dragging it turns the view, the way dragging the model
// does: by the turntable 'viewpoint.ts' describes, about Z. Clicking a ball looks
// along that axis from that end, as the button for it under the gizmo does. The
// arrow keys turn it a step at a time, for whoever is not using a mouse.
//
// It is a 2D canvas rather than a second three.js scene: it is a dozen shapes,
// it has to draw on tabs that have no 3D renderer at all (a picture is all the
// 2D and Simulation tabs have), and a GPU context is a scarce thing that the
// panel's real views need more.
//

import { AxisView, Viewpoint, DEFAULT_VIEWPOINT, projectAxes } from './viewpoint';

export interface GizmoCallbacks {
    /** Turned by hand, by these angles in radians; 'final' once the drag is over and the view is to be kept. */
    onOrbit: (azimuth: number, polar: number, final: boolean) => void;
    /** A ball was clicked: look along that axis, from that end. */
    onPick: (axis: AxisView) => void;
}

/** The colour of each axis: a triad's, a step softer, so that a ball can carry a letter. */
const AXIS_COLORS: Record<'x' | 'y' | 'z', string> = { x: '#e5484d', y: '#30a46c', z: '#3e7bfa' };

/** How far a pointer has to move before a press is a drag rather than a click, in pixels. */
const DRAG_THRESHOLD = 3;

/** How far one arrow key turns the view: a twelfth of a turn. */
const KEY_STEP = Math.PI / 12;

export class Gizmo {
    public readonly element: HTMLCanvasElement;
    private viewpoint: Viewpoint = DEFAULT_VIEWPOINT;
    private hovered: AxisView | undefined;
    private enabled = true;
    private press: { x: number; y: number; dragging: boolean; id: number } | undefined;

    /** 'size' is the side of the square it is drawn in, in CSS pixels. */
    constructor(
        private readonly callbacks: GizmoCallbacks,
        private readonly size = 112,
    ) {
        this.element = document.createElement('canvas');
        this.element.className = 'view-gizmo';
        this.element.tabIndex = 0;
        this.element.setAttribute('role', 'img');
        this.element.setAttribute('aria-label', 'Orientation: drag to turn the view, click an axis to look along it');
        this.element.title = 'Drag to turn the view; click an axis to look along it';
        this.element.style.width = `${size}px`;
        this.element.style.height = `${size}px`;
        this.element.addEventListener('pointerdown', (event) => this.down(event));
        this.element.addEventListener('pointermove', (event) => this.move(event));
        this.element.addEventListener('pointerup', (event) => this.up(event));
        this.element.addEventListener('pointercancel', (event) => this.up(event, true));
        this.element.addEventListener('pointerleave', () => this.hover(undefined));
        this.element.addEventListener('keydown', (event) => this.key(event));
        this.draw();
    }

    /** Draw the axes as they lie from 'viewpoint'. */
    public set(viewpoint: Viewpoint): void {
        this.viewpoint = viewpoint;
        this.draw();
    }

    /** Take input, or not: 'title' is why not, and the gizmo goes on showing the view either way. */
    public setEnabled(enabled: boolean, title?: string): void {
        this.enabled = enabled;
        this.element.classList.toggle('disabled', !enabled);
        this.element.title = enabled ? 'Drag to turn the view; click an axis to look along it' : (title ?? '');
        this.element.tabIndex = enabled ? 0 : -1;
        if (!enabled) {
            this.press = undefined;
            this.hovered = undefined;
        }
        this.draw();
    }

    /** Where each ball is drawn, in CSS pixels from the canvas's corner, farthest first. */
    private layout(): { axis: AxisView; x: number; y: number; depth: number; radius: number }[] {
        const middle = this.size / 2;
        const reach = middle - 13;
        return projectAxes(this.viewpoint).map((end) => ({
            axis: end.axis,
            x: middle + end.x * reach,
            y: middle - end.y * reach,
            depth: end.depth,
            radius: end.axis.startsWith('-') ? 7 : 10,
        }));
    }

    /** The ball under a point, nearest the reader first. */
    private hit(x: number, y: number): AxisView | undefined {
        const balls = this.layout().reverse();
        return balls.find((ball) => Math.hypot(ball.x - x, ball.y - y) <= ball.radius + 2)?.axis;
    }

    private point(event: PointerEvent): { x: number; y: number } {
        const box = this.element.getBoundingClientRect();
        return { x: event.clientX - box.left, y: event.clientY - box.top };
    }

    private down(event: PointerEvent): void {
        if (!this.enabled || event.button !== 0) {
            return;
        }
        const { x, y } = this.point(event);
        this.press = { x, y, dragging: false, id: event.pointerId };
        this.element.setPointerCapture?.(event.pointerId);
        event.preventDefault();
    }

    private move(event: PointerEvent): void {
        if (!this.enabled) {
            return;
        }
        const { x, y } = this.point(event);
        const press = this.press;
        if (press === undefined || press.id !== event.pointerId) {
            this.hover(this.hit(x, y));
            return;
        }
        const dx = x - press.x;
        const dy = y - press.y;
        if (!press.dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) {
            return;
        }
        press.dragging = true;
        press.x = x;
        press.y = y;
        // Half a turn across the gizmo, either way: the model turns with the
        // pointer, as it does when it is dragged on the canvas.
        const rate = Math.PI / this.size;
        this.callbacks.onOrbit(-dx * rate, -dy * rate, false);
    }

    private up(event: PointerEvent, cancelled = false): void {
        const press = this.press;
        if (press === undefined || press.id !== event.pointerId) {
            return;
        }
        this.press = undefined;
        this.element.releasePointerCapture?.(event.pointerId);
        if (press.dragging) {
            this.callbacks.onOrbit(0, 0, true);
            return;
        }
        if (cancelled) {
            return;
        }
        const { x, y } = this.point(event);
        const axis = this.hit(x, y);
        if (axis !== undefined) {
            this.callbacks.onPick(axis);
        }
    }

    private key(event: KeyboardEvent): void {
        if (!this.enabled) {
            return;
        }
        // As dragging that way would: left turns the model left, up turns it up.
        const step: [number, number] | undefined =
            event.key === 'ArrowLeft'
                ? [KEY_STEP, 0]
                : event.key === 'ArrowRight'
                  ? [-KEY_STEP, 0]
                  : event.key === 'ArrowUp'
                    ? [0, KEY_STEP]
                    : event.key === 'ArrowDown'
                      ? [0, -KEY_STEP]
                      : undefined;
        if (step === undefined) {
            return;
        }
        event.preventDefault();
        this.callbacks.onOrbit(step[0], step[1], true);
    }

    private hover(axis: AxisView | undefined): void {
        if (axis === this.hovered) {
            return;
        }
        this.hovered = axis;
        this.element.style.cursor = axis !== undefined ? 'pointer' : '';
        this.draw();
    }

    private draw(): void {
        const context = this.element.getContext?.('2d');
        if (!context) {
            return;
        }
        const ratio = window.devicePixelRatio || 1;
        const pixels = Math.round(this.size * ratio);
        if (this.element.width !== pixels || this.element.height !== pixels) {
            this.element.width = pixels;
            this.element.height = pixels;
        }
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, this.size, this.size);

        const style = getComputedStyle(this.element);
        const foreground = style.color || '#888';
        const family = style.fontFamily || 'sans-serif';
        const middle = this.size / 2;

        // The disc it turns in, faintly, so that it reads as something to grab.
        context.globalAlpha = this.press?.dragging ? 0.16 : 0.08;
        context.fillStyle = foreground;
        context.beginPath();
        context.arc(middle, middle, middle - 1, 0, Math.PI * 2);
        context.fill();

        for (const ball of this.layout()) {
            const letter = ball.axis.replace('-', '') as 'x' | 'y' | 'z';
            const color = AXIS_COLORS[letter];
            const negative = ball.axis.startsWith('-');
            const near = (ball.depth + 1) / 2;
            context.globalAlpha = 0.45 + 0.55 * near;
            if (!negative) {
                context.strokeStyle = color;
                context.lineWidth = 2;
                context.beginPath();
                context.moveTo(middle, middle);
                context.lineTo(ball.x, ball.y);
                context.stroke();
            }
            const lit = ball.axis === this.hovered;
            context.beginPath();
            context.arc(ball.x, ball.y, ball.radius + (lit ? 1.5 : 0), 0, Math.PI * 2);
            context.fillStyle = color;
            if (negative) {
                context.globalAlpha *= lit ? 0.9 : 0.4;
                context.fill();
                context.globalAlpha = 0.45 + 0.55 * near;
                context.lineWidth = 1.5;
                context.strokeStyle = color;
                context.stroke();
            } else {
                context.fill();
            }
            if (!negative || lit) {
                context.globalAlpha = 1;
                context.fillStyle = '#ffffff';
                context.font = `600 ${negative ? 8 : 11}px ${family}`;
                context.textAlign = 'center';
                context.textBaseline = 'middle';
                context.fillText(negative ? `-${letter.toUpperCase()}` : letter.toUpperCase(), ball.x, ball.y + 0.5);
            }
        }
        context.globalAlpha = 1;
    }
}
