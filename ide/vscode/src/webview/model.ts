//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A small glTF viewer for a pane that is not the 3D one.
//
// 'scene.ts' is the PartCAD Viewer's 3D view, and it is deliberately not
// reusable: it is one canvas with a rig tuned to match what partcad.org shows,
// down to the lights it borrows from 'react-partcad-prerendered'. Making a part
// look the way a part looks there is its whole job.
//
// A CAM preview is a different thing to look at and wants a different picture:
// what is worth seeing in a toolpath is its structure - where the walls are,
// where the fill goes, where the gaps between them are - so it is drawn plainly
// and lit evenly rather than staged. This class is that: one container, one
// model, no shadows, no auto-rotation, and a camera the reader drives.
//
// Like everything else in the webview it makes no network request. The model
// arrives over postMessage as base64 binary glTF and is parsed out of memory.
//

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

/** How much bigger than the model the camera's distance is. */
const FRAMING = 2.2;

export class ModelView {
    /**
     * The element to put in a pane.
     *
     * Owned by this object rather than by the pane, because the pane is emptied
     * whenever it is filled in again and the WebGL context inside this must
     * outlive that: a context is expensive to make and browsers keep only a
     * handful of them alive at once.
     */
    public readonly element: HTMLDivElement;

    private readonly renderer: THREE.WebGLRenderer;
    private readonly scene: THREE.Scene;
    private readonly camera: THREE.PerspectiveCamera;
    private readonly controls: OrbitControls;
    private model: THREE.Group | undefined;
    private running = false;

    constructor() {
        this.element = document.createElement('div');
        this.element.className = 'viewer';

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.setClearColor(0x000000, 0);
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        this.element.appendChild(this.renderer.domElement);

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, 1, 0.001, 10000);
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;

        // Even light from three directions rather than a staged rig: a toolpath
        // is read for its structure, and a dramatic key light hides half of it
        // in its own shadow.
        this.scene.add(new THREE.AmbientLight(0xffffff, 1.2));
        const key = new THREE.DirectionalLight(0xffffff, 1.6);
        key.position.set(1, 2, 1.5);
        const fill = new THREE.DirectionalLight(0xffffff, 0.8);
        fill.position.set(-1.5, -0.5, -1);
        this.scene.add(key, fill);

        window.addEventListener('resize', () => this.resize());
    }

    /** Draw one binary glTF, replacing whatever was there. */
    public async show(gltf: ArrayBuffer): Promise<void> {
        this.dispose();
        const loaded = await new Promise<THREE.Group>((resolve, reject) => {
            new GLTFLoader().parse(gltf, '', (result) => resolve(result.scene), reject);
        });

        loaded.traverse((node) => {
            const mesh = node as THREE.Mesh;
            if (!mesh.isMesh) {
                return;
            }
            const previous = mesh.material as THREE.Material | THREE.Material[] | undefined;
            // One material for everything, so that what varies in the picture is
            // the geometry - which is the only thing that carries meaning here.
            mesh.material = new THREE.MeshPhongMaterial({ color: 0x3fae4a, shininess: 30 });
            disposeMaterials(previous);
        });

        this.model = loaded;
        this.scene.add(loaded);
        this.frame();
        this.resize();
        this.start();
    }

    /** Give up the GPU resources of whatever is on screen. */
    public dispose(): void {
        this.running = false;
        if (this.model === undefined) {
            return;
        }
        this.scene.remove(this.model);
        disposeTree(this.model);
        this.model = undefined;
    }

    /** Fit the canvas to the pane, which has no size at all while it is hidden. */
    public resize(): void {
        const width = this.element.clientWidth;
        const height = this.element.clientHeight;
        if (width === 0 || height === 0) {
            return;
        }
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    }

    private frame(): void {
        if (this.model === undefined) {
            return;
        }
        const box = new THREE.Box3().setFromObject(this.model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const reach = Math.max(size.x, size.y, size.z) || 1;

        this.controls.target.copy(center);
        this.camera.near = reach / 1000;
        this.camera.far = reach * 100;
        this.camera.position.set(center.x + reach, center.y + reach * 0.8, center.z + reach * FRAMING);
        this.camera.updateProjectionMatrix();
        this.controls.update();
    }

    private start(): void {
        if (this.running) {
            return;
        }
        this.running = true;
        const tick = () => {
            if (!this.running) {
                return;
            }
            requestAnimationFrame(tick);
            this.controls.update();
            this.renderer.render(this.scene, this.camera);
        };
        tick();
    }
}

function disposeMaterials(material: THREE.Material | THREE.Material[] | undefined): void {
    if (material === undefined) {
        return;
    }
    for (const one of Array.isArray(material) ? material : [material]) {
        one.dispose();
    }
}

function disposeTree(root: THREE.Object3D): void {
    root.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (!mesh.isMesh) {
            return;
        }
        mesh.geometry?.dispose();
        disposeMaterials(mesh.material as THREE.Material | THREE.Material[] | undefined);
    });
}

/** The bytes of a base64 payload, as the loader wants them. */
export function base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}
