//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 3D view's renderer of last resort: the scene painted into a 2D canvas on
// the CPU, for a window that has neither WebGL nor WebGPU.
//
// Painting a scene is a painter's algorithm: every triangle is projected onto the
// screen, the triangles are sorted far to near, and each is filled over whatever
// is behind it, in one flat colour worked out from the lights. three's
// 'Projector' does the first two - it is the half of its 'SVGRenderer' that does
// not touch the DOM - and this is the other half, written into pixels.
//
// Into pixels and not into SVG, which is where the time goes: the SVG renderer
// makes a DOM element per triangle and the browser lays every one of them out,
// and measured on the same scene that is 2.5 to 3.5 times slower than filling the
// same triangles into a canvas (18 against 5 ms at 16,000 triangles, 77 against
// 32 at 65,000). Projecting is a fifth of the canvas time or less.
//
// What it does not do is what a painter's algorithm cannot: two triangles that
// cross are drawn one over the other whole, and a long thin one can be sorted
// behind a neighbour it is in front of. 'scene.ts' draws solids front-side only
// for that reason - a closed solid's far side is then never drawn at all.
//

import * as THREE from 'three';
import { Projector, RenderableFace, RenderableLine } from 'three/examples/jsm/renderers/Projector.js';

/**
 * How far each triangle is grown on screen, in pixels, before it is filled.
 *
 * Two triangles sharing an edge are filled separately, and the anti-aliased
 * edge of each lets the background through along the seam: a hairline over
 * every face of the mesh. Grown by this much, neighbours overlap instead.
 */
const OVERDRAW = 1;

export class CanvasPainter {
    readonly domElement = document.createElement('canvas');
    private readonly context = this.domElement.getContext('2d') as CanvasRenderingContext2D;
    private readonly projector = new Projector();
    private width = 1;
    private height = 1;
    private ratio = 1;

    // Scratch values, reused for every element of every frame.
    private readonly ambient = new THREE.Color();
    private readonly lit = new THREE.Color();
    private readonly direction = new THREE.Vector3();
    private readonly target = new THREE.Vector3();
    private readonly normal = new THREE.Vector3();
    private readonly points = [new THREE.Vector2(), new THREE.Vector2(), new THREE.Vector2()];

    setPixelRatio(ratio: number): void {
        this.ratio = ratio;
        this.setSize(this.width, this.height);
    }

    setSize(width: number, height: number): void {
        this.width = width;
        this.height = height;
        this.domElement.width = Math.max(1, Math.round(width * this.ratio));
        this.domElement.height = Math.max(1, Math.round(height * this.ratio));
    }

    render(scene: THREE.Scene, camera: THREE.Camera): void {
        const context = this.context;
        context.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
        // Transparent, like the GPU renderers' canvas: the panel's background is
        // the editor's.
        context.clearRect(0, 0, this.width, this.height);

        // Far to near: 'sortElements' is what makes this a painter's algorithm.
        const data = this.projector.projectScene(scene, camera, true, true);
        const lights = data.lights as THREE.Light[];
        this.ambient.setRGB(0, 0, 0);
        for (const light of lights) {
            if ((light as THREE.AmbientLight).isAmbientLight) {
                this.ambient.r += light.color.r * light.intensity;
                this.ambient.g += light.color.g * light.intensity;
                this.ambient.b += light.color.b * light.intensity;
            }
        }

        for (const element of data.elements) {
            if (element instanceof RenderableFace) {
                this.face(element, lights);
            } else if (element instanceof RenderableLine) {
                this.line(element);
            }
        }
        context.globalAlpha = 1;
    }

    /** Where a projected vertex lands on the canvas, in CSS pixels. */
    private screen(vertex: { positionScreen: THREE.Vector4 }, into: THREE.Vector2): THREE.Vector2 {
        return into.set(
            ((vertex.positionScreen.x + 1) * this.width) / 2,
            ((1 - vertex.positionScreen.y) * this.height) / 2,
        );
    }

    private face(face: RenderableFace, lights: THREE.Light[]): void {
        const material = face.material as THREE.MeshPhongMaterial | null;
        if (material === null || !material.visible) {
            return;
        }
        const [a, b, c] = this.points;
        this.screen(face.v1, a);
        this.screen(face.v2, b);
        this.screen(face.v3, c);
        grow(a, b, c);

        const color = this.lit;
        if ((material as unknown as THREE.MeshBasicMaterial).isMeshBasicMaterial) {
            // Unlit: a port's boundary is the colour it was given, whichever way
            // it faces.
            color.copy(material.color);
        } else {
            this.shade(face, lights, color);
            color.multiply(material.color);
            if (material.emissive) {
                color.add(material.emissive);
            }
        }

        const context = this.context;
        context.globalAlpha = material.transparent ? material.opacity : 1;
        context.fillStyle = style(color);
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.lineTo(c.x, c.y);
        context.closePath();
        context.fill();
    }

    /** How much light falls on a face: the ambient light, and each directional one it faces. */
    private shade(face: RenderableFace, lights: THREE.Light[], into: THREE.Color): void {
        into.copy(this.ambient);
        this.normal.copy(face.normalModel).normalize();
        for (const light of lights) {
            const directional = light as THREE.DirectionalLight;
            if (!directional.isDirectionalLight) {
                continue;
            }
            // From the target to the light, as the GPU renderers read it.
            this.direction.setFromMatrixPosition(directional.matrixWorld);
            this.target.setFromMatrixPosition(directional.target.matrixWorld);
            this.direction.sub(this.target).normalize();
            const amount = this.normal.dot(this.direction);
            if (amount > 0) {
                into.r += light.color.r * light.intensity * amount;
                into.g += light.color.g * light.intensity * amount;
                into.b += light.color.b * light.intensity * amount;
            }
        }
    }

    private line(line: RenderableLine): void {
        const material = line.material as THREE.LineBasicMaterial | null;
        if (material === null || !material.visible) {
            return;
        }
        const [a, b] = this.points;
        this.screen(line.v1, a);
        this.screen(line.v2, b);
        // An axes triad colours each line by its vertices; anything else is the
        // material's colour.
        const color = material.vertexColors ? line.vertexColors[0] : material.color;
        const context = this.context;
        context.globalAlpha = material.transparent ? material.opacity : 1;
        context.strokeStyle = style(color);
        context.lineWidth = Math.max(1, material.linewidth ?? 1);
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.stroke();
    }
}

const clamped = new THREE.Color();

/**
 * A colour as a canvas takes it.
 *
 * three keeps colours linear, which is what lighting arithmetic needs, and the
 * GPU renderers convert to sRGB on the way to the screen. A canvas takes sRGB
 * and nothing else, so the conversion is done here - which is what 'getStyle'
 * does - or every face comes out darker and more saturated than it is.
 */
function style(color: THREE.Color): string {
    clamped.setRGB(Math.min(1, color.r), Math.min(1, color.g), Math.min(1, color.b));
    return clamped.getStyle();
}

/** Move each corner of a triangle away from its centre by 'OVERDRAW' pixels. */
function grow(a: THREE.Vector2, b: THREE.Vector2, c: THREE.Vector2): void {
    const cx = (a.x + b.x + c.x) / 3;
    const cy = (a.y + b.y + c.y) / 3;
    for (const point of [a, b, c]) {
        const dx = point.x - cx;
        const dy = point.y - cy;
        const length = Math.hypot(dx, dy);
        if (length > 0) {
            point.x += (dx / length) * OVERDRAW;
            point.y += (dy / length) * OVERDRAW;
        }
    }
}
