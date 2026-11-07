//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The page 'test_viewer_render.py' renders finishes in: the 3D view's own
// finished materials ('finish.ts' for WebGL, 'finishNode.ts' for WebGPU), on a
// sphere under the 3D view's own light rig ('scene.ts'), read back in linear
// light before tone mapping, so that the test can compare each pixel with what
// 'raster_scene.finished_light' says it is.
//
// Bundled by the test (esbuild), with 'three' from the extension's own
// node_modules; nothing here is shipped.
//

import * as THREE from 'three';
import * as WEBGPU from 'three/webgpu';

import { applyFinish, setFinishShown } from '../../../ide/vscode/src/webview/finish';
import { finishedNodeMaterial } from '../../../ide/vscode/src/webview/finishNode';

// 'ROOM_LIGHT' and 'STAGE_INTENSITY' of 'scene.ts', and the rig 'frame()' places
// for an object of radius 1.
const ROOM_LIGHT = [3.78, 1.73, 1.59, 0.26, 0.19, 1.03, 1.19, -0.34, -0.63].flatMap((band) => [band, band, band]);
const STAGE = 0.5;
const SIZE = 64;
const STEP = 6;

interface Case {
    color: number;
    finish?: { roughness: number; metallic: number };
    plain?: boolean;
    textured?: boolean;
}

function stage() {
    const scene = new THREE.Scene();
    const probe = new THREE.LightProbe(new THREE.SphericalHarmonics3().fromArray(ROOM_LIGHT), STAGE);
    const ambient = new THREE.AmbientLight(0xffffff, STAGE / 3);
    const hemisphere = new THREE.HemisphereLight(0xffffff, 0x000000, 0.7);
    const spot = new THREE.SpotLight(0xffffff, 2 * STAGE, 0, Math.PI / 4, 1, 0);
    spot.position.set(2, 4, 2);
    const point = new THREE.PointLight(0xffffff, STAGE, 0, 0);
    point.position.set(-2, 1, -2);
    scene.add(probe, ambient, spot, spot.target, point, hemisphere, new THREE.PointLight(0xffffff, 1, 0, 0));
    scene.updateMatrixWorld(true);
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    camera.position.set(1.5, 1.2, 3.5);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld();
    return { scene, camera, rig: { probe, ambient, hemisphere } };
}

/** An image of one pixel, in 'color': drawn with it, a face is that colour, as the render takes it. */
function pixelOf(color: number): THREE.Texture {
    const texture = new THREE.DataTexture(
        new Uint8Array([(color >> 16) & 255, (color >> 8) & 255, color & 255, 255]),
        1,
        1,
        THREE.RGBAFormat,
    );
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.needsUpdate = true;
    return texture;
}

/** Where on the unit sphere each sampled pixel is, and what it was drawn as. */
function samples(camera: THREE.Camera, pixels: Float32Array, rowsDown: boolean) {
    const found: { p: number[]; rgb: number[] }[] = [];
    for (let y = STEP / 2; y < SIZE; y += STEP) {
        for (let x = STEP / 2; x < SIZE; x += STEP) {
            const far = new THREE.Vector3(((x + 0.5) / SIZE) * 2 - 1, ((y + 0.5) / SIZE) * 2 - 1, 0.5).unproject(camera);
            const ray = far.sub(camera.position).normalize();
            const along = camera.position.dot(ray);
            const disc = along * along - (camera.position.lengthSq() - 1);
            // Not off the sphere, nor at its rim, where a pixel is half of it.
            if (disc < 0.05) {
                continue;
            }
            const point = camera.position.clone().addScaledVector(ray, -along - Math.sqrt(disc));
            const row = rowsDown ? SIZE - 1 - y : y;
            const i = (row * SIZE + x) * 4;
            found.push({ p: point.toArray(), rgb: [pixels[i], pixels[i + 1], pixels[i + 2]] });
        }
    }
    return found;
}

async function run(backend: 'webgl' | 'webgpu', cases: Case[]) {
    const { scene, camera, rig } = stage();
    const geometry = new THREE.SphereGeometry(1, 256, 128);
    const drawn: { eye: number[]; samples: { p: number[]; rgb: number[] }[] }[] = [];
    if (backend === 'webgl') {
        const renderer = new THREE.WebGLRenderer({ canvas: document.createElement('canvas') });
        renderer.toneMapping = THREE.NoToneMapping;
        const target = new THREE.WebGLRenderTarget(SIZE, SIZE, { type: THREE.FloatType });
        for (const c of cases) {
            const material = new THREE.MeshPhongMaterial(
                c.textured ? { color: 0xffffff, map: pixelOf(c.color) } : { color: c.color },
            );
            if (c.finish) {
                applyFinish(material, c.textured ? 0xffffff : c.color, c.finish, c.color);
            }
            const mesh = new THREE.Mesh(geometry, material);
            scene.add(mesh);
            renderer.setRenderTarget(target);
            renderer.render(scene, camera);
            // Switched after its program is built: the switch is values, not a program.
            if (c.plain) {
                setFinishShown(material, false);
                renderer.render(scene, camera);
            }
            const pixels = new Float32Array(SIZE * SIZE * 4);
            renderer.readRenderTargetPixels(target, 0, 0, SIZE, SIZE, pixels);
            scene.remove(mesh);
            drawn.push({ eye: camera.position.toArray(), samples: samples(camera, pixels, false) });
        }
        return { backend, drawn };
    }
    const renderer = new WEBGPU.WebGPURenderer({ canvas: document.createElement('canvas') } as never);
    try {
        await renderer.init();
    } catch (error) {
        return { backend, unavailable: String(error) };
    }
    if (!(renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend) {
        return { backend, unavailable: 'three fell back to WebGL 2: this browser has no WebGPU adapter' };
    }
    renderer.toneMapping = THREE.NoToneMapping;
    const target = new WEBGPU.RenderTarget(SIZE, SIZE, { type: THREE.FloatType });
    for (const c of cases) {
        const parameters = c.textured ? { color: 0xffffff, map: pixelOf(c.color) } : { color: c.color };
        const material = c.finish
            ? finishedNodeMaterial(parameters, c.textured ? 0xffffff : c.color, c.finish, c.color, rig)
            : new THREE.MeshPhongMaterial(parameters);
        const mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        renderer.setRenderTarget(target);
        renderer.render(scene, camera);
        if (c.plain) {
            setFinishShown(material, false);
            renderer.render(scene, camera);
        }
        const pixels = (await renderer.readRenderTargetPixelsAsync(target, 0, 0, SIZE, SIZE)) as Float32Array;
        scene.remove(mesh);
        // A WebGPU texture's rows run top to bottom.
        drawn.push({ eye: camera.position.toArray(), samples: samples(camera, pixels, true) });
    }
    return { backend, drawn };
}

(window as unknown as { run: typeof run }).run = run;
