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
// A face with a finish is lit as 'finish.ts' says - its diffuse light, a
// highlight from each light, and the room it reflects - by this painter's own
// lights and in its own arithmetic ('finished'): flat, one colour per triangle,
// like everything it draws.
//
// What it does not do is what a painter's algorithm cannot: two triangles that
// cross are drawn one over the other whole, and a long thin one can be sorted
// behind a neighbour it is in front of. 'scene.ts' draws solids front-side only
// for that reason - a closed solid's far side is then never drawn at all.
//

import * as THREE from 'three';
import { Projector, RenderableFace, RenderableLine } from 'three/examples/jsm/renderers/Projector.js';

import { FinishState, blinnPhong, roomFresnel, shownFinish } from './finish';

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
    /** The flat colour of a face drawn with an image, which this painter cannot draw. */
    private readonly flat = new THREE.Color();
    private readonly direction = new THREE.Vector3();
    private readonly target = new THREE.Vector3();
    private readonly normal = new THREE.Vector3();
    private readonly eye = new THREE.Vector3();
    private readonly view = new THREE.Vector3();
    private readonly mirrored = new THREE.Vector3();
    private readonly half = new THREE.Vector3();
    private readonly toward = new THREE.Vector3();
    private readonly term = new THREE.Color();
    private readonly fresnel = new THREE.Color();
    private readonly room = new THREE.Color();
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
        this.eye.setFromMatrixPosition(camera.matrixWorld);
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
            const finish = shownFinish(material);
            if (finish !== undefined) {
                this.finished(face, lights, finish, color);
            } else {
                this.normal.copy(face.normalModel).normalize();
                this.shade(this.normal, lights, color);
                // A face drawn with an image is one flat colour here: the colour it
                // is drawn as where an image cannot be (see 'Geometry.faceMaterial').
                const flat = material.map ? material.userData.flatColor : undefined;
                color.multiply(
                    typeof flat === 'number' ? this.flat.setHex(flat, THREE.SRGBColorSpace) : material.color,
                );
            }
            if (material.emissive) {
                color.add(material.emissive);
            }
        }
        if (material.vertexColors && Number.isFinite(face.color.r)) {
            // A result plot's colours are per vertex, and they are the answer.
            // 'Projector' gives a face the colour of its first vertex, which is
            // as near as one flat colour per triangle comes; three multiplies
            // it into the material's colour, and so does this. A geometry with
            // no colours to give leaves the face's unset, and the material's
            // colour stands.
            color.multiply(face.color);
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

    /**
     * How much light falls on a face: the ambient light, each hemisphere light,
     * and each directional one it faces.
     *
     * Not three's arithmetic to the letter: its Lambert term divides by pi, and
     * this does not, so a pane that lights the same scene for both gives the
     * painter its intensities over pi (see 'cae.ts').
     */
    private shade(normal: THREE.Vector3, lights: THREE.Light[], into: THREE.Color): THREE.Color {
        into.copy(this.ambient);
        for (const light of lights) {
            const hemisphere = light as THREE.HemisphereLight;
            if (hemisphere.isHemisphereLight) {
                // The sky's colour on a face turned to it, the ground's on one
                // turned away, and a blend between - as three's shader has it.
                this.direction.setFromMatrixPosition(hemisphere.matrixWorld).normalize();
                const sky = 0.5 * normal.dot(this.direction) + 0.5;
                into.r +=
                    (hemisphere.groundColor.r + (light.color.r - hemisphere.groundColor.r) * sky) * light.intensity;
                into.g +=
                    (hemisphere.groundColor.g + (light.color.g - hemisphere.groundColor.g) * sky) * light.intensity;
                into.b +=
                    (hemisphere.groundColor.b + (light.color.b - hemisphere.groundColor.b) * sky) * light.intensity;
                continue;
            }
            const directional = light as THREE.DirectionalLight;
            if (!directional.isDirectionalLight) {
                continue;
            }
            // From the target to the light, as the GPU renderers read it.
            this.direction.setFromMatrixPosition(directional.matrixWorld);
            this.target.setFromMatrixPosition(directional.target.matrixWorld);
            this.direction.sub(this.target).normalize();
            const amount = normal.dot(this.direction);
            if (amount > 0) {
                into.r += light.color.r * light.intensity * amount;
                into.g += light.color.g * light.intensity * amount;
                into.b += light.color.b * light.intensity * amount;
            }
        }
        return into;
    }

    /**
     * The colour of a face drawn with its finish, seen from the camera: three's
     * Phong arithmetic times pi, as 'shade' is.
     *
     * The light falling on it times its diffuse colour; for each directional
     * light, the Blinn-Phong highlight of its specular colour and shininess; and
     * the room it mirrors - 'shade' of the mirrored view direction - by
     * 'roomFresnel'. All from the colour it is drawn as where an image cannot be
     * ('FinishState.flat'), since an image is one flat colour here. Lit from the
     * side it is seen from, as the GPU renderers light a two-sided face.
     */
    private finished(face: RenderableFace, lights: THREE.Light[], finish: FinishState, into: THREE.Color): void {
        const look = finish.flat;
        const normal = this.normal.copy(face.normalModel).normalize();
        // Seen from the middle of the triangle.
        const view = this.view
            .copy(face.v1.positionWorld)
            .add(face.v2.positionWorld)
            .add(face.v3.positionWorld)
            .multiplyScalar(1 / 3);
        view.subVectors(this.eye, view).normalize();
        if (normal.dot(view) < 0) {
            normal.negate();
        }
        this.shade(normal, lights, into).multiply(look.color);
        for (const light of lights) {
            const directional = light as THREE.DirectionalLight;
            if (!directional.isDirectionalLight) {
                continue;
            }
            const toward = this.toward.setFromMatrixPosition(directional.matrixWorld);
            toward.sub(this.target.setFromMatrixPosition(directional.target.matrixWorld)).normalize();
            const dotNL = normal.dot(toward);
            if (dotNL <= 0) {
                continue;
            }
            const half = this.half.addVectors(toward, view).normalize();
            blinnPhong(look.specular, look.shininess, normal.dot(half), Math.max(0, view.dot(half)), this.term);
            this.term.multiply(light.color).multiplyScalar(Math.PI * light.intensity * dotNL);
            into.add(this.term);
        }
        const dotNV = Math.max(0, normal.dot(view));
        const mirrored = this.mirrored
            .copy(normal)
            .multiplyScalar(2 * dotNV)
            .sub(view);
        roomFresnel(look.specular, dotNV, finish.finish.roughness, this.fresnel);
        into.add(this.shade(mirrored, lights, this.room).multiply(this.fresnel));
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
