//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD Viewer's 3D view: the renderer behind the first tab of the panel.
//
// Runs inside the webview, not in the extension host, so it has no access to
// 'vscode' or to node - the geometry arrives over postMessage as base64 binary
// glTF and is parsed straight out of memory. There is deliberately no network
// request anywhere in this file; the panel's CSP forbids one.
//
// The presentation follows 'react-partcad-prerendered' (see its
// 'src/components/Part.js'), which is the viewer PartCAD already ships on the
// web, so that a part looks the same in the IDE as it does on partcad.org:
//
//   * an auto-rotating orbit camera, framed on the model;
//   * drei's <Stage> lighting - an environment map plus an ambient/spot/point
//     trio scaled from the model's size - with contact shadows underneath;
//   * the hemisphere and point lights Part.js adds on top of Stage;
//   * MeshPhongMaterial;
//   * a loading overlay showing the model size and progress.
//
// Two deliberate departures from Part.js, both forced by the webview: React and
// react-three-fiber are not used (a lot of bundle for one canvas), and the
// environment is three's procedural RoomEnvironment rather than drei's
// environment="city" preset, which is an HDRI fetched from a CDN that the CSP
// blocks and that would not work offline.
//
// A third difference is not a choice. Part.js loads OBJ, a format with no scene
// graph and no units, so it has to rotate the model by -90 degrees about X
// itself to stand PartCAD's Z-up geometry up in a Y-up scene. glTF has both:
// build123d's export_gltf writes that same rotation into the node transform and
// converts millimetres to glTF's metres, so the model arrives correctly oriented
// and rotating it again here would lay it on its side. Only the port markers,
// which come from PartCAD as raw millimetre Z-up locations rather than through
// the exporter, still need the conversion applied - see MM_TO_M/Z_UP_TO_Y_UP.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

import { reportError } from './host';
import { ShowMarker, ShowMessage } from './messages';

// Part.js: <Stage intensity={0.5}> and MeshPhongMaterial with no arguments.
const STAGE_INTENSITY = 0.5;
// Part.js: <OrbitControls autoRotate={true} autoRotateSpeed={5.0} />
const AUTO_ROTATE_SPEED = 5.0;
// The two conversions build123d's export_gltf bakes into the geometry it writes,
// and which therefore have to be applied by hand to anything that does not go
// through it - the port markers. glTF's unit is the metre and its up axis is Y;
// PartCAD's locations are in millimetres about a Z-up frame.
const MM_TO_M = 0.001;
const Z_UP_TO_Y_UP = -Math.PI / 2;

const container = document.getElementById('viewer') as HTMLDivElement;
const overlay = document.getElementById('overlay') as HTMLDivElement;
const label = document.getElementById('label') as HTMLDivElement;

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
// The panel's background is the editor's, so the canvas stays transparent and
// the viewer follows the user's colour theme rather than fighting it.
renderer.setClearColor(0x000000, 0);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10000);
camera.position.set(0, 0, 5);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = AUTO_ROTATE_SPEED;

// An environment map stands in for drei's <Environment preset="...">: image
// based lighting is what makes a machined surface read as one. RoomEnvironment
// is generated in code, so it costs no asset and works offline.
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = STAGE_INTENSITY;

// <Stage>'s light rig, plus the two lights Part.js adds itself. Positions are
// set from the model's size in frame(), because a rig scaled for a 10 mm part
// lights a 2 m assembly not at all.
//
// Every positional light here has decay 0 - no inverse-square falloff - which
// is what makes these intensities mean the same thing whatever size the model
// is. With three's default physical decay of 2, irradiance is intensity/d², and
// glTF is in metres: a 10 mm part sits ~0.03 units from the rig, so intensity 1
// would arrive as ~1000 and burn the model to a white silhouette. (Part.js gets
// away with the default because its OBJ models are in millimetres, where the
// same lights land three orders of magnitude weaker and contribute almost
// nothing.) Turning decay off is the scale-invariant reading of that rig.
const ambientLight = new THREE.AmbientLight(0xffffff, STAGE_INTENSITY / 3);
const spotLight = new THREE.SpotLight(0xffffff, 2 * STAGE_INTENSITY, 0, Math.PI / 4, 1, 0);
spotLight.castShadow = true;
spotLight.shadow.mapSize.set(1024, 1024);
const stagePointLight = new THREE.PointLight(0xffffff, STAGE_INTENSITY, 0, 0);
// Part.js: <hemisphereLight color="#40c040" intensity={0.7} groundColor="black" />
const hemisphereLight = new THREE.HemisphereLight(0x40c040, 0x000000, 0.7);
// Part.js: <pointLight intensity={1} />, at the scene origin.
const partPointLight = new THREE.PointLight(0xffffff, 1, 0, 0);
scene.add(ambientLight, spotLight, stagePointLight, hemisphereLight, partPointLight);

// <Stage shadows="contact">: a shadow catcher under the model. ShadowMaterial
// keeps the plane itself invisible, so only the shadow lands on the background.
const shadowPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.ShadowMaterial({ opacity: 0.35, transparent: true }),
);
shadowPlane.rotation.x = -Math.PI / 2;
shadowPlane.receiveShadow = true;
scene.add(shadowPlane);

/** Everything the current show put on the stage; replaced wholesale by the next. */
let content: THREE.Group | undefined;

/**
 * Which show is the current one.
 *
 * Parsing a glTF is asynchronous, so a second show (or a clear) can arrive and
 * finish while the first is still decoding its objects. Without this, the older
 * call would go on to install its now-stale model over the newer one - visible
 * as the viewer showing the previously selected part after a quick change of
 * selection, or after a save that re-renders. Every show takes a generation on
 * entry and abandons its work as soon as it is no longer the newest.
 */
let generation = 0;

const loader = new GLTFLoader();

function base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}

function parseGltf(buffer: ArrayBuffer): Promise<THREE.Group> {
    return new Promise((resolve, reject) => {
        // parse(), not load(): the bytes are already here, and load() would mean
        // a URL and therefore a network request the CSP forbids.
        loader.parse(buffer, '', (gltf) => resolve(gltf.scene), reject);
    });
}

/**
 * Let go of a material and of the textures it holds.
 *
 * 'Material.dispose()' frees the shader program and nothing else: a texture can
 * be shared between materials, so three.js leaves it to the application to say
 * when one is finished with. Here every texture came out of the glTF being
 * discarded and is referenced by nothing outside it, and 'dispose()' is
 * idempotent, so one shared between two materials of the same file is simply
 * disposed twice.
 */
function disposeMaterial(material: THREE.Material): void {
    for (const value of Object.values(material)) {
        const texture = value as THREE.Texture | undefined;
        if (texture?.isTexture) {
            texture.dispose();
        }
    }
    material.dispose();
}

/** The same, for the one-or-many a mesh's 'material' can be. */
function disposeMaterials(material: THREE.Material | THREE.Material[] | undefined): void {
    if (Array.isArray(material)) {
        material.forEach(disposeMaterial);
    } else if (material) {
        disposeMaterial(material);
    }
}

function disposeTree(root: THREE.Object3D): void {
    root.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (mesh.geometry) {
            mesh.geometry.dispose();
        }
        disposeMaterials(mesh.material as THREE.Material | THREE.Material[] | undefined);
    });
}

export function clearGeometry(): void {
    // Takes a generation too, so a show still decoding cannot undo the clear.
    generation += 1;
    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
        content = undefined;
    }
    label.textContent = '';
    overlay.textContent = 'Nothing to display yet.';
    overlay.style.display = '';
}

/**
 * Center the model at the origin and frame the camera on it, as
 * <Stage adjustCamera> does, and scale the light rig and shadow catcher to it.
 */
function frame(group: THREE.Group, keepCamera: boolean): void {
    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) {
        return;
    }

    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) / 2 || 1;

    // Stage centers the model rather than moving the camera to it, so that
    // orbiting turns the model about itself.
    group.position.sub(center);

    shadowPlane.position.y = -size.y / 2;
    shadowPlane.scale.setScalar(radius * 8);

    spotLight.position.set(radius * 2, radius * 4, radius * 2);
    spotLight.shadow.camera.near = radius * 0.1;
    spotLight.shadow.camera.far = radius * 20;
    stagePointLight.position.set(-radius * 2, radius, -radius * 2);
    // Part.js leaves this one at the scene origin, i.e. inside the model.
    partPointLight.position.set(0, 0, 0);

    camera.near = radius / 100;
    camera.far = radius * 100;
    camera.updateProjectionMatrix();

    if (!keepCamera) {
        // Far enough back that the bounding sphere fits the vertical field of
        // view, with the same slight elevation Stage's default camera has.
        const distance = (radius * 1.6) / Math.tan((camera.fov * Math.PI) / 360);
        camera.position.set(distance * 0.6, distance * 0.5, distance * 0.8);
        controls.target.set(0, 0, 0);
    }
    controls.update();
}

function addMarkers(parent: THREE.Group, markers: ShowMarker[], size: number): void {
    if (markers.length === 0) {
        return;
    }

    // The markers are raw PartCAD locations: millimetres, Z-up. Putting them
    // under a group that carries the same conversion export_gltf applies to the
    // geometry is what lines the two up, and keeps each marker's own transform
    // expressed in the frame PartCAD stated it in.
    const frame = new THREE.Group();
    frame.rotation.set(Z_UP_TO_Y_UP, 0, 0);
    frame.scale.setScalar(MM_TO_M);
    parent.add(frame);

    for (const marker of markers) {
        const [translation, axis, angle] = marker.location;
        // A port is a coordinate frame and has no geometry of its own, so it is
        // drawn as a triad - the same thing showing a bare location used to give.
        const axes = new THREE.AxesHelper(size);
        axes.position.set(translation[0], translation[1], translation[2]);
        const direction = new THREE.Vector3(axis[0], axis[1], axis[2]);
        if (direction.lengthSq() > 0) {
            axes.quaternion.setFromAxisAngle(direction.normalize(), (angle * Math.PI) / 180);
        }
        axes.name = marker.name ?? 'port';
        frame.add(axes);
    }
}

export async function showGeometry(message: ShowMessage): Promise<void> {
    const mine = (generation += 1);
    const superseded = () => generation !== mine;

    const totalSize = message.objects.reduce((sum, object) => sum + object.size, 0);
    overlay.style.display = '';
    overlay.textContent = `Model size: ${(totalSize / 1048576.0).toFixed(2)}MB\n0% loaded`;

    const group = new THREE.Group();

    let loaded = 0;
    for (const object of message.objects) {
        let parsed: THREE.Group;
        try {
            parsed = await parseGltf(base64ToArrayBuffer(object.gltf));
        } catch (error: any) {
            reportError(`failed to parse '${object.name}': ${error}`);
            continue;
        }

        if (superseded()) {
            // Something newer arrived while this object was decoding. Drop what
            // has been built so far rather than paint it over the newer state -
            // and what was just parsed with it, which is not in the group yet
            // and so is not reached by disposing that.
            disposeTree(parsed);
            disposeTree(group);
            return;
        }

        parsed.traverse((node) => {
            const mesh = node as THREE.Mesh;
            if (!mesh.isMesh) {
                return;
            }
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            // Part.js replaces whatever material the file carries with a plain
            // MeshPhongMaterial, which is what gives every PartCAD model the
            // same look regardless of how it was authored.
            const previous = mesh.material as THREE.Material | THREE.Material[] | undefined;
            mesh.material = new THREE.MeshPhongMaterial();
            disposeMaterials(previous);
        });
        parsed.name = object.name;
        group.add(parsed);

        loaded += object.size;
        const percent = totalSize > 0 ? Math.round((loaded / totalSize) * 100) : 100;
        overlay.textContent = `Model size: ${(totalSize / 1048576.0).toFixed(2)}MB\n${percent}% loaded`;
    }

    // The triads are built inside the millimetre frame, so their length is in
    // millimetres too: a quarter of the model's largest dimension, or 10 mm when
    // there is no geometry to measure against (an interface with bare ports).
    const geometryBox = new THREE.Box3().setFromObject(group);
    const largest = geometryBox.isEmpty() ? 0 : Math.max(...geometryBox.getSize(new THREE.Vector3()).toArray());
    addMarkers(group, message.markers ?? [], largest > 0 ? largest / 4 / MM_TO_M : 10);

    if (superseded()) {
        disposeTree(group);
        return;
    }

    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
    }
    content = group;
    scene.add(group);
    frame(group, message.keepCamera);

    label.textContent = message.name ?? '';
    overlay.style.display = 'none';
}

export function resizeCanvas(): void {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (width === 0 || height === 0) {
        return;
    }
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

function animate(): void {
    controls.update();
    renderer.render(scene, camera);
}

window.addEventListener('resize', resizeCanvas);
resizeCanvas();
renderer.setAnimationLoop(animate);
