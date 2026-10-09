//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What a 3D pane of the panel draws with: the GPU through WebGL, the GPU through
// WebGPU, or the CPU into a canvas - the first of the three this window can give.
//
// Every pane that draws in 3D asks here rather than building a renderer of its
// own: the 3D view ('scene.ts') and the model an analysis produced ('cae.ts').
// A pane that built a 'THREE.WebGLRenderer' itself was a pane that drew nothing
// in a window with no WebGL, however well the one beside it coped.
//
// WebGL is the ordinary case and the one everything here was written for. Its
// constructor throws when there is no context - in a virtual machine, over a
// remote desktop, on a Linux box whose GPU process failed - and a pane used to
// end there. Now it goes on to the next:
//
//   * WebGPU, through three's 'WebGPURenderer', where the window has an adapter
//     to give it - a GPU that WebGL could not use but WebGPU can, or Chromium's
//     software fallback adapter. The same scene, lit the same way. Its build of
//     three shares this one's core ('three.core.js'), so the meshes and
//     materials a pane makes are the ones it draws. Loaded only when it is
//     needed, and given up on - for the canvas - if it does not start.
//   * The canvas painter ('painter.ts'): the scene projected on the CPU and its
//     triangles filled far to near, flat-shaded. No GPU at all, and slower for
//     it - so a pane drawn this way draws only when something changed, and a
//     big model is drawn as boxes while the camera is being moved ('boxesOf').
//
// A backend that failed once is not asked again by the next pane: the answer
// does not change while the window is open, and asking again would put the same
// failure in the log once per analysis.
//

import * as THREE from 'three';

import { el } from './dom';
import { noWebGL, reportError } from './host';
import { CanvasPainter } from './painter';

export type Backend = 'webgl' | 'webgpu' | 'software';

export interface Surface {
    readonly backend: Backend;
    readonly domElement: HTMLElement;
    setSize(width: number, height: number): void;
    render(scene: THREE.Scene, camera: THREE.Camera): void;
    /** Image-based lighting, where the backend can make it; undefined where it cannot. */
    environment?(scene: THREE.Scene): THREE.Texture | undefined;
    /** Draw every frame, through the backend's own loop. Absent for the painter, which draws on demand. */
    setAnimationLoop?(callback: (() => void) | null): void;
    /** What the performance readout reports, where the backend counts it. */
    readonly info?: { render: { calls: number; triangles: number }; memory: { geometries: number; textures: number } };
    /** Give the context back. A browser keeps a handful of GPU contexts and drops the oldest past that. */
    dispose(): void;
}

/** Why there is no WebGL, in three's words, for the notice that says so. */
let noWebGLReason: string | undefined;

/** The backends that failed in this window, which the next pane does not try again. */
const failed = new Set<Backend>();

/** What a pane wants of its surface beyond a picture. */
export interface SurfaceOptions {
    /**
     * How a GPU maps light to the screen. The 3D view's studio wants a filmic
     * curve; an analysis result, whose colours are the answer, wants none. The
     * painter has no such curve whichever is asked for.
     */
    toneMapping?: THREE.ToneMapping;
}

/**
 * Why this window has no WebGL 2, or undefined when it has.
 *
 * Asked of a throwaway canvas before three is, because three says so on the
 * console - three 'console.error' lines for a window that merely has no GPU -
 * and then throws, which is the case this file exists to handle quietly. A
 * console error is what a broken pane looks like (and what the IDE's end to end
 * test fails on), so a missing GPU must not produce one. The browser's own
 * reason, when it gives one, is what the notice's tooltip quotes.
 */
function webglUnavailable(): string | undefined {
    const canvas = document.createElement('canvas');
    let reason: string | undefined;
    canvas.addEventListener(
        'webglcontextcreationerror',
        (event) => {
            reason = (event as WebGLContextEvent).statusMessage || reason;
        },
        { once: true },
    );
    let context: WebGL2RenderingContext | null = null;
    try {
        context = canvas.getContext('webgl2');
    } catch (error: unknown) {
        return error instanceof Error ? error.message : String(error);
    }
    if (context === null) {
        return reason || 'WebGL 2 is not available in this window';
    }
    // Given back at once: a window has a small budget of live contexts.
    context.getExtension('WEBGL_lose_context')?.loseContext();
    return undefined;
}

function webglSurface(options: SurfaceOptions): Surface | undefined {
    const unavailable = webglUnavailable();
    if (unavailable !== undefined) {
        noWebGLReason = unavailable;
        return undefined;
    }
    let renderer: THREE.WebGLRenderer;
    try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (error: unknown) {
        noWebGLReason = error instanceof Error ? error.message : String(error);
        return undefined;
    }
    renderer.setPixelRatio(window.devicePixelRatio);
    // The panel's background is the editor's, so the canvas stays transparent and
    // the viewer follows the user's colour theme rather than fighting it.
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = options.toneMapping ?? THREE.NoToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    return {
        backend: 'webgl',
        domElement: renderer.domElement,
        setSize: (width, height) => renderer.setSize(width, height, false),
        render: (scene, camera) => renderer.render(scene, camera),
        environment: (scene) => new THREE.PMREMGenerator(renderer).fromScene(scene, 0.04).texture,
        setAnimationLoop: (callback) => renderer.setAnimationLoop(callback),
        info: renderer.info,
        dispose: () => {
            renderer.setAnimationLoop(null);
            renderer.dispose();
        },
    };
}

/** Whether a WebGPU renderer has drawn the probe in this window, which then need not be drawn again. */
let webgpuProven = false;

/** What three's WebGPU build is, as far as this file needs it. */
type WebGPUModule = typeof import('three/webgpu');
type WebGPURenderer = InstanceType<WebGPUModule['WebGPURenderer']>;

/** The part of a 'GPUDevice' used here; the WebGPU types are not in this compilation's lib. */
interface Device {
    pushErrorScope(filter: 'validation'): void;
    popErrorScope(): Promise<{ message: string } | null>;
    readonly lost: Promise<{ message: string }>;
}

/**
 * Keep a lost device from being reported as a crash, and say whether it was lost.
 *
 * three pushes an error scope around every pipeline it builds and pops it with a
 * '.then()' and no '.catch()'. A device that is lost - which is how a window
 * whose GPU process cannot present a WebGPU canvas answers the first frame -
 * rejects every scope still open, and each rejection reached the window's trap
 * ('host.ts') as "The PartCAD Viewer hit an error", written over a view that had
 * already gone on to draw without the GPU. So on a device this file made, a
 * scope that cannot be popped because the device is gone has nothing to report
 * but that, which the returned function then says.
 */
function watchDevice(device: Device): () => string | undefined {
    let lost: string | undefined;
    void device.lost.then((info) => {
        lost ??= info.message || 'the WebGPU device was lost';
    });
    const pop = device.popErrorScope.bind(device);
    device.popErrorScope = () =>
        pop().catch((error: unknown) => {
            lost ??= String(error);
            return null;
        });
    return () => lost;
}

/**
 * Draw, once and out of sight, what the panes draw: every kind of material they
 * make, lines, and an environment map.
 *
 * An adapter and a renderer that initialised do not make a renderer that draws.
 * three's WebGPU build is written against the specification as it is now, and a
 * Chromium older than a change to it rejects what three sends - r185 names a
 * texture view's swizzle as a string, which a Chromium that still took it as a
 * dictionary refuses with a 'TypeError' from every 'createView'. That fails on
 * the first frame and every frame after, and a 3D view that accepted WebGPU on
 * the strength of 'init()' drew nothing and filled the log. So a renderer is
 * accepted only once it has drawn this - with whatever the GPU validates
 * asynchronously caught as well - and the next of the three is used otherwise.
 */
async function probe(
    webgpu: WebGPUModule,
    renderer: WebGPURenderer,
    device: Device,
    lost: () => string | undefined,
): Promise<void> {
    device.pushErrorScope('validation');
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10);
    camera.position.set(0, 0, 3);
    const box = new THREE.BoxGeometry();
    box.setAttribute('color', new THREE.BufferAttribute(new Float32Array(box.getAttribute('position').count * 3), 3));
    const materials: THREE.Material[] = [
        new THREE.MeshPhongMaterial({ side: THREE.DoubleSide }),
        new THREE.MeshLambertMaterial({ vertexColors: true }),
        new THREE.MeshStandardMaterial(),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.5 }),
    ];
    const lines = new THREE.LineBasicMaterial({ vertexColors: true });
    const axes = new THREE.AxesHelper();
    axes.material = lines;
    scene.add(...materials.map((material) => new THREE.Mesh(box, material)), axes);
    scene.add(new THREE.AmbientLight(), new THREE.DirectionalLight(), new THREE.HemisphereLight());
    const generator = new webgpu.PMREMGenerator(renderer);
    const environment = generator.fromScene(new THREE.Scene(), 0.04);
    scene.environment = environment.texture;
    try {
        renderer.render(scene, camera);
    } finally {
        environment.dispose();
        generator.dispose();
        box.dispose();
        axes.geometry.dispose();
        lines.dispose();
        materials.forEach((material) => material.dispose());
    }
    const error = await device.popErrorScope();
    if (error) {
        throw new Error(error.message);
    }
    const reason = lost();
    if (reason !== undefined) {
        throw new Error(reason);
    }
}

async function webgpuSurface(what: string, options: SurfaceOptions): Promise<Surface | undefined> {
    const gpu = (navigator as Navigator & { gpu?: { requestAdapter(options?: object): Promise<unknown> } }).gpu;
    if (gpu === undefined) {
        return undefined;
    }
    let renderer: WebGPURenderer | undefined;
    try {
        // Asked before three is: 'WebGPURenderer' falls back to WebGL 2 by itself
        // when there is no adapter, and there is no WebGL here - so a renderer it
        // made would fail later rather than now.
        const adapter = (await gpu.requestAdapter()) ?? (await gpu.requestAdapter({ forceFallbackAdapter: true }));
        if (!adapter) {
            return undefined;
        }
        const WEBGPU = await import(/* webpackMode: "eager" */ 'three/webgpu');
        const gpuRenderer = new WEBGPU.WebGPURenderer({ antialias: true, alpha: true });
        renderer = gpuRenderer;
        await gpuRenderer.init();
        const device = (gpuRenderer.backend as unknown as { device: Device }).device;
        const lost = watchDevice(device);
        gpuRenderer.setPixelRatio(window.devicePixelRatio);
        gpuRenderer.setClearColor(0x000000, 0);
        gpuRenderer.toneMapping = options.toneMapping ?? THREE.NoToneMapping;
        gpuRenderer.outputColorSpace = THREE.SRGBColorSpace;
        if (!webgpuProven) {
            await probe(WEBGPU, gpuRenderer, device, lost);
            webgpuProven = true;
        }
        // Proven is not promised: a frame that throws after all is said once,
        // not sixty times a second for as long as the panel is open.
        let broken = false;
        return {
            backend: 'webgpu',
            domElement: gpuRenderer.domElement,
            setSize: (width, height) => gpuRenderer.setSize(width, height, false),
            render: (scene, camera) => {
                if (broken) {
                    return;
                }
                try {
                    gpuRenderer.render(scene, camera);
                } catch (error: unknown) {
                    broken = true;
                    reportError(`${what} stopped drawing with WebGPU: ${error}`);
                }
            },
            environment: (scene) => new WEBGPU.PMREMGenerator(gpuRenderer).fromScene(scene, 0.04).texture,
            setAnimationLoop: (callback) => void gpuRenderer.setAnimationLoop(callback),
            info: gpuRenderer.info as unknown as Surface['info'],
            dispose: () => {
                void gpuRenderer.setAnimationLoop(null);
                gpuRenderer.dispose();
            },
        };
    } catch (error: unknown) {
        // Reported, and not fatal: the canvas is still there to draw with.
        renderer?.dispose();
        reportError(`${what} could not use WebGPU, and draws without the GPU: ${error}`);
        return undefined;
    }
}

function softwareSurface(): Surface {
    const painter = new CanvasPainter();
    painter.setPixelRatio(window.devicePixelRatio);
    return {
        backend: 'software',
        domElement: painter.domElement,
        setSize: (width, height) => painter.setSize(width, height),
        render: (scene, camera) => painter.render(scene, camera),
        dispose: () => undefined,
    };
}

/**
 * The first of WebGL, WebGPU and the canvas painter this window can give.
 *
 * 'what' names the pane, for the log line that says WebGPU would not start.
 */
export async function createSurface(what: string, options: SurfaceOptions = {}): Promise<Surface> {
    if (!failed.has('webgl')) {
        const surface = webglSurface(options);
        if (surface !== undefined) {
            return surface;
        }
        failed.add('webgl');
    }
    if (!failed.has('webgpu')) {
        const surface = await webgpuSurface(what, options);
        if (surface !== undefined) {
            return surface;
        }
        failed.add('webgpu');
    }
    return softwareSurface();
}

/**
 * The note in the corner of a pane drawn without a GPU.
 *
 * Said, small and out of the way: the pane works, and the reader should know
 * why it is flat-shaded and slower than it could be - and how to have the GPU
 * back, which is the advice a pane used to give instead of a picture. Placed by
 * '.software-notice', so its parent has to be positioned.
 */
export function softwareNotice(): HTMLElement {
    const notice = el('div', 'software-notice', 'Drawn without a graphics card');
    notice.title = noWebGL(noWebGLReason ?? 'WebGL is not available');
    return notice;
}

/**
 * How many triangles the software renderer draws while the camera is moving.
 *
 * Above it, a frame is long enough that a drag stutters, so while one lasts the
 * model is drawn as the outline of each of its pieces' boxes - which says where
 * everything is and moves at once - and in full again when it is let go.
 */
export const SOFTWARE_TRIANGLE_BUDGET = 60000;

export function trianglesOf(object: THREE.Object3D): number {
    let count = 0;
    object.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (!mesh.isMesh || mesh.geometry === undefined) {
            return;
        }
        const geometry = mesh.geometry as THREE.BufferGeometry;
        const vertices = geometry.index?.count ?? geometry.getAttribute('position')?.count ?? 0;
        count += vertices / 3;
    });
    return count;
}

/**
 * A box per mesh of 'object', where each one is now, in a hidden group.
 *
 * What a big model is drawn as by the painter while the camera moves. The group
 * is meant to be added to the scene itself, not under 'object', and is placed in
 * world coordinates; 'disposeBoxes' frees it.
 */
export function boxesOf(object: THREE.Object3D, color: THREE.ColorRepresentation): THREE.Group {
    object.updateMatrixWorld(true);
    const boxes = new THREE.Group();
    boxes.visible = false;
    object.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (!mesh.isMesh) {
            return;
        }
        const box = new THREE.Box3().setFromObject(mesh);
        if (!box.isEmpty()) {
            boxes.add(new THREE.Box3Helper(box, color));
        }
    });
    return boxes;
}

export function disposeBoxes(boxes: THREE.Group): void {
    boxes.removeFromParent();
    boxes.traverse((node) => {
        const helper = node as THREE.Box3Helper;
        helper.geometry?.dispose();
        (helper.material as THREE.Material | undefined)?.dispose();
    });
}
