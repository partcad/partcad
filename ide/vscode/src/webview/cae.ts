//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The FEA and CFD tabs: the model an analysis produced, and what it found.
//
// The pane is three bands, top to bottom:
//
//   * the implementation, in a field over the middle of the pane. It is the
//     one thing about an analysis a user changes without editing a file - which
//     solver ran it - and it is pre-filled with whichever one did, so that
//     "CalculiX is not installed here" is a sentence with a box under it to type
//     the answer into rather than an error and nowhere to go.
//   * the model. Which of the two viewers draws it is decided by the file
//     extension, because *which format* is the implementation's choice and not
//     PartCAD's: a 3D field is turned and zoomed with an orbit camera, a 2D plot
//     is a still image that pans and zooms.
//   * the findings, in the bottom fifth of the pane - and only when there are
//     any. An analysis that found nothing is a pass, and a pass should give the
//     model the whole pane rather than a strip of white space with "none" in it.
//
// The 3D viewer here is deliberately *not* 'scene.ts'. That one is a studio: an
// environment map, a light rig, contact shadows, auto-rotation - everything that
// makes a machined part look like a machined part. An analysis result is the
// opposite kind of picture. Its colours are the answer, so relighting them is
// falsifying them, and it is read rather than admired, so it must hold still.
// Two renderers with opposite jobs are clearer than one with a mode switch, and
// this one is built only once something 3D actually arrives.
//

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { el, empty, placeholder } from './dom';
import { CaeData, CaeFinding } from './messages';

/** How much of the pane the findings take when there are any. */
const FINDINGS_SHARE = '20%';

/** The still-image formats the 2D viewer can show, by file extension. */
const IMAGE_TYPES: Record<string, string> = {
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    gif: 'image/gif',
    webp: 'image/webp',
    // Shown through an <img>, which cannot run script in it whatever the file
    // says. Never inlined into the DOM: the panel's CSP would not stop an
    // inlined <svg> from carrying an <a> or a <foreignObject>.
    svg: 'image/svg+xml',
};

/** The mesh formats the 3D viewer can load, by file extension. */
const MESH_TYPES = new Set(['glb', 'gltf', 'stl']);

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 20;

function decodeBase64(content: string): Uint8Array {
    const binary = atob(content);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

/**
 * A still image that pans and zooms.
 *
 * A 2D analysis plot is a picture with numbers written on it, and the numbers
 * are small: the whole point of it being 2D is that it is read closely. So the
 * wheel zooms about the pointer and a drag moves the image, which is what every
 * other image viewer does and therefore what nobody has to be told.
 */
class ImageView {
    private readonly image = el('img', 'cae-image');
    private scale = 1;
    private x = 0;
    private y = 0;
    private dragging: { x: number; y: number } | undefined;

    constructor(private readonly host: HTMLElement) {
        host.classList.add('cae-canvas', 'cae-image-host');
        host.appendChild(this.image);
        this.image.draggable = false;

        host.addEventListener('wheel', (event: WheelEvent) => {
            event.preventDefault();
            const rect = host.getBoundingClientRect();
            // Zoom about the pointer rather than the centre: the thing being
            // looked at should stay under the cursor.
            const px = event.clientX - rect.left;
            const py = event.clientY - rect.top;
            const factor = Math.exp(-event.deltaY / 400);
            const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, this.scale * factor));
            const applied = next / this.scale;
            this.x = px - (px - this.x) * applied;
            this.y = py - (py - this.y) * applied;
            this.scale = next;
            this.apply();
        });
        host.addEventListener('pointerdown', (event: PointerEvent) => {
            this.dragging = { x: event.clientX - this.x, y: event.clientY - this.y };
            host.setPointerCapture(event.pointerId);
        });
        host.addEventListener('pointermove', (event: PointerEvent) => {
            if (this.dragging === undefined) {
                return;
            }
            this.x = event.clientX - this.dragging.x;
            this.y = event.clientY - this.dragging.y;
            this.apply();
        });
        const release = (event: PointerEvent) => {
            this.dragging = undefined;
            if (host.hasPointerCapture(event.pointerId)) {
                host.releasePointerCapture(event.pointerId);
            }
        };
        host.addEventListener('pointerup', release);
        host.addEventListener('pointercancel', release);
        host.addEventListener('dblclick', () => this.reset());
    }

    public show(source: string, alt: string): void {
        this.image.src = source;
        this.image.alt = alt;
        this.reset();
    }

    private reset(): void {
        this.scale = 1;
        this.x = 0;
        this.y = 0;
        this.apply();
    }

    private apply(): void {
        this.image.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    }
}

/**
 * A mesh, turned and zoomed with an orbit camera.
 *
 * Built the first time a 3D result arrives and kept afterwards: a WebGL context
 * is not free, and there are already two panes in this panel that want one.
 */
class MeshView {
    private readonly renderer: THREE.WebGLRenderer;
    private readonly scene = new THREE.Scene();
    private readonly camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100000);
    private readonly controls: OrbitControls;
    private model: THREE.Object3D | undefined;
    private running = false;

    constructor(private readonly host: HTMLElement) {
        host.classList.add('cae-canvas');
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.setClearColor(0x000000, 0);
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        host.appendChild(this.renderer.domElement);

        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;

        // Flat, even light and nothing else. A result plot's colours are the
        // answer; a rig that shades them is a rig that changes the answer.
        this.scene.add(new THREE.AmbientLight(0xffffff, 2.2));
        const fill = new THREE.HemisphereLight(0xffffff, 0x444444, 1.0);
        this.scene.add(fill);

        new ResizeObserver(() => this.resize()).observe(host);
    }

    public async show(bytes: Uint8Array, extension: string): Promise<void> {
        const object = extension === 'stl' ? loadStl(bytes) : await loadGltf(bytes, extension);
        if (this.model !== undefined) {
            this.scene.remove(this.model);
            dispose(this.model);
        }
        this.model = object;
        this.scene.add(object);
        this.frame(object);
        this.resize();
        this.start();
    }

    /** Put the whole model in view, whatever units and origin it came in. */
    private frame(object: THREE.Object3D): void {
        const box = new THREE.Box3().setFromObject(object);
        if (box.isEmpty()) {
            return;
        }
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const extent = Math.max(size.x, size.y, size.z) || 1;
        const distance = extent * 2.2;

        this.camera.near = extent / 1000;
        this.camera.far = extent * 100;
        this.camera.position.set(center.x + distance, center.y + distance * 0.6, center.z + distance);
        this.camera.updateProjectionMatrix();
        this.controls.target.copy(center);
        this.controls.update();
    }

    private start(): void {
        if (this.running) {
            return;
        }
        this.running = true;
        const tick = () => {
            this.controls.update();
            this.renderer.render(this.scene, this.camera);
            requestAnimationFrame(tick);
        };
        tick();
    }

    /** Match the canvas to the pane, which has no size at all while hidden. */
    public resize(): void {
        const width = this.host.clientWidth;
        const height = this.host.clientHeight;
        if (width === 0 || height === 0) {
            return;
        }
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height, false);
    }
}

function loadStl(bytes: Uint8Array): THREE.Object3D {
    const geometry = new STLLoader().parse(toArrayBuffer(bytes));
    geometry.computeVertexNormals();
    // 'vertexColors' costs nothing when the file carries none, and a result mesh
    // that does carry them is a result mesh whose colours are the finding.
    const material = new THREE.MeshLambertMaterial({
        color: 0xbfc4c9,
        vertexColors: geometry.hasAttribute('color'),
        side: THREE.DoubleSide,
    });
    return new THREE.Mesh(geometry, material);
}

async function loadGltf(bytes: Uint8Array, extension: string): Promise<THREE.Object3D> {
    const loader = new GLTFLoader();
    const buffer = toArrayBuffer(bytes);
    return await new Promise<THREE.Object3D>((resolve, reject) => {
        try {
            // A '.gltf' may be JSON pointing at files beside it, which a webview
            // has no way to fetch - and must not try to: the CSP forbids it. The
            // empty resource path makes any such reference fail as the error it
            // is, rather than as a silent half-loaded model.
            loader.parse(buffer, '', (gltf) => resolve(gltf.scene), reject);
        } catch (error: unknown) {
            reject(error instanceof Error ? error : new Error(`${extension}: ${error}`));
        }
    });
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

function dispose(object: THREE.Object3D): void {
    object.traverse((node: THREE.Object3D) => {
        const mesh = node as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material;
        if (Array.isArray(material)) {
            material.forEach((one) => one.dispose());
        } else {
            material?.dispose();
        }
    });
}

/**
 * One analysis tab.
 *
 * It owns its pane outright - the header, the model band and the findings band -
 * and hands 'onRun' whatever the user typed into the implementation field.
 * Fetching is the shell's job ('viewer.ts'), the same as for every other tab.
 */
export class CaeView {
    private readonly field = el('input', 'cae-implementation') as HTMLInputElement;
    private readonly body = el('div', 'cae-body');
    private readonly model = el('div', 'cae-model');
    private readonly findings = el('div', 'cae-findings');
    private imageView: ImageView | undefined;
    private meshView: MeshView | undefined;

    constructor(pane: HTMLElement, analysis: string, onRun: (implementation: string) => void) {
        pane.classList.add('cae');

        const header = el('div', 'cae-header');
        this.field.type = 'text';
        this.field.spellcheck = false;
        this.field.placeholder = '<package>:<file type>';
        this.field.title =
            `Which implementation runs the ${analysis.toUpperCase()}, as '<package>:<file type>'. ` +
            `The same thing 'pc cae ${analysis} --implementation' names`;
        this.field.setAttribute('aria-label', `${analysis.toUpperCase()} implementation`);

        const run = el('button', 'cae-run', 'Run');
        const fire = () => onRun(this.field.value.trim());
        run.addEventListener('click', fire);
        this.field.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter') {
                fire();
            }
        });

        header.appendChild(el('span', 'cae-header-label', 'Implementation'));
        header.appendChild(this.field);
        header.appendChild(run);

        this.body.appendChild(this.model);
        this.body.appendChild(this.findings);
        pane.appendChild(header);
        pane.appendChild(this.body);

        this.setBusy('Waiting for PartCAD…');
    }

    /** Pre-fill the field with what the host used, without disturbing a typed value. */
    public suggest(implementation: string | undefined): void {
        if (implementation && document.activeElement !== this.field) {
            this.field.value = implementation;
        }
    }

    /** The pane while the solver is running, which is not a quick thing. */
    public setBusy(text: string): void {
        this.showFindings([]);
        empty(this.model);
        this.model.appendChild(placeholder(text));
    }

    /** A refusal, which for these two tabs is usually the answer itself. */
    public showError(message: string): void {
        this.showFindings([]);
        empty(this.model);
        this.model.appendChild(el('p', 'error', message));
    }

    public render(data: CaeData): void {
        this.suggest(data.implementation);
        this.showFindings(data.findings ?? []);
        empty(this.model);

        const extension = (data.extension || '').toLowerCase();
        if (!data.content) {
            // The analysis ran and the model did not come back: the daemon says
            // so in the log, and the findings above are the half that matters.
            this.model.appendChild(placeholder(`The model was written to ${data.filepath}.`));
            return;
        }

        if (IMAGE_TYPES[extension] !== undefined) {
            // A fresh one each time: 'this.model' was emptied above, so the
            // previous view's <img> and its listeners went with it.
            this.imageView = new ImageView(this.model);
            this.imageView.show(
                `data:${IMAGE_TYPES[extension]};base64,${data.content}`,
                `${data.analysis.toUpperCase()} result for ${data.object}`,
            );
            return;
        }

        if (MESH_TYPES.has(extension)) {
            const view = new MeshView(this.model);
            this.meshView = view;
            void view.show(decodeBase64(data.content), extension).catch((error: unknown) => {
                empty(this.model);
                this.model.appendChild(el('p', 'error', `Failed to display the model: ${error}`));
            });
            return;
        }

        // A format the panel cannot draw is not a failed analysis. The findings
        // are above it and the file is on disk; say where, and name what could
        // have been drawn so an implementation author knows what to write.
        this.model.appendChild(
            placeholder(
                `PartCAD cannot draw a '.${extension}' here. The model is at ${data.filepath}.\n` +
                    `Drawable here: ${[...MESH_TYPES].join(', ')} in 3D, ${Object.keys(IMAGE_TYPES).join(', ')} as a picture.`,
            ),
        );
    }

    /** The canvas had no size while the tab was hidden; WebGL does not notice. */
    public resize(): void {
        this.meshView?.resize();
    }

    /**
     * The findings band: the bottom fifth of the pane, and nothing at all when
     * there are none.
     */
    private showFindings(findings: CaeFinding[]): void {
        empty(this.findings);
        this.findings.hidden = findings.length === 0;
        this.model.style.height = findings.length === 0 ? '100%' : `calc(100% - ${FINDINGS_SHARE})`;
        if (findings.length === 0) {
            return;
        }
        this.findings.style.height = FINDINGS_SHARE;

        const heading = el(
            'div',
            'cae-findings-heading',
            `${findings.length} finding${findings.length === 1 ? '' : 's'}`,
        );
        this.findings.appendChild(heading);

        const list = el('ul', 'cae-findings-list');
        for (const finding of findings) {
            const item = el('li', 'cae-finding');
            const severity = String(finding.severity ?? 'warning').toLowerCase();
            item.appendChild(el('span', `cae-severity cae-severity-${severity.replace(/[^a-z]/g, '')}`, severity));
            item.appendChild(el('span', 'cae-finding-message', String(finding.message ?? '')));
            const where = finding.where ?? null;
            if (where) {
                item.appendChild(el('span', 'cae-finding-where', String(where)));
            }
            list.appendChild(item);
        }
        this.findings.appendChild(list);
    }
}
