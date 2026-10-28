//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The player the Simulation tab plays the video of a run in.
//
// Video.js 10 (`@videojs/html`), composed from its parts rather than one of its
// packaged skins, for one reason: full screen. A skin's full-screen button
// hides itself where the Fullscreen API is not allowed, and a Visual Studio
// Code webview is exactly such a place -- its iframes carry no
// `allow="fullscreen"` -- so a skin would offer no full screen at all, and a
// skin's controls cannot be added to. Composed, the controls are the usual
// ones -- play and pause (and replay at the end), a step back and forward, a
// position to drag, the time, the speed -- and full screen is a button of our
// own: the Fullscreen API where there is one, and where there is none the
// player filling the whole panel while the host takes the editor full screen
// ('onFullscreen'; Zen Mode, in 'PartcadViewer.ts').
//
// Until it is played, the player shows the run's two pictures -- before on the
// left, after on the right, an arrow between them -- as one still, drawn here
// into a canvas the shape of the video ('still').
//
// Kept out of 'simulation.ts', which only asks for a player through
// 'SimulationCallbacks.player': Video.js is published as ES modules alone, and
// the extension's tests run the panes under CommonJS, with no DOM. 'viewer.ts'
// hands this in.
//

import '@videojs/html/video/player';
import '@videojs/html/ui/container';
import '@videojs/html/ui/controls';
import '@videojs/html/ui/controls-content';
import '@videojs/html/ui/controls-group';
import '@videojs/html/ui/gesture';
import '@videojs/html/ui/hotkey';
import '@videojs/html/ui/play-button';
import '@videojs/html/ui/playback-rate-button';
import '@videojs/html/ui/poster';
import '@videojs/html/ui/seek-button';
import '@videojs/html/ui/slider-fill';
import '@videojs/html/ui/slider-thumb';
import '@videojs/html/ui/slider-track';
import '@videojs/html/ui/time';
import '@videojs/html/ui/time-group';
import '@videojs/html/ui/time-separator';
import '@videojs/html/ui/time-slider';
import {
    fullscreenEnterIcon,
    fullscreenExitIcon,
    pauseIcon,
    playIcon,
    restartIcon,
    seekIcon,
} from '@videojs/html/icons';

import { SimulationImage } from './messages';
import type { SimulationPlayer, SimulationStill } from './simulation';

/** How far the step buttons and the arrow keys move, in seconds: a tenth of the default run. */
const STEP = 1;

/** What a still is drawn on: the snapshots' own background, so that the two pictures sit on it seamlessly. */
const STILL_BACKGROUND = '#f7f7fa';
const STILL_INK = '#6b6f76';

/** What a still is drawn the shape of when the video does not say: HD. */
const STILL_SIZE = { width: 1280, height: 720 };

export interface VideoPlayerOptions {
    /**
     * The player went full screen, or came back, without the Fullscreen API:
     * filling the panel, which is all a webview can do, and the host is asked
     * to make the panel fill the screen.
     */
    onFullscreen: (on: boolean) => void;
}

/**
 * A player for the video of a run, with the run's pictures as its still.
 *
 * What 'SimulationCallbacks.player' is: 'viewer.ts' binds 'options' and hands
 * the rest to the Simulation tab.
 */
export function createVideoPlayer(
    recording: SimulationImage,
    still: SimulationStill,
    options: VideoPlayerOptions,
): SimulationPlayer {
    const element = node('div', 'simulation-video');
    const player = node('video-player');
    const container = node('media-container', 'simulation-video-surface');
    container.tabIndex = 0;
    container.setAttribute('aria-label', 'The video of the simulation');

    const video = document.createElement('video');
    video.className = 'simulation-video-media';
    video.preload = 'auto';
    video.playsInline = true;
    video.muted = true;
    const url = feed(video, recording.content, recording.extension);

    // The still: the pictures, once they are drawn into one. Handed to the
    // player as its 'poster', which is where '<media-poster>' takes the source
    // of its image from -- it keeps the image's 'src' in step with that, so one
    // set on the image itself would not last.
    const poster = node('media-poster', 'simulation-video-poster');
    const posterImage = document.createElement('img');
    posterImage.alt = 'The scene before the simulation on the left, and after it on the right';
    poster.appendChild(posterImage);

    // A click on the picture plays and pauses, as on every player.
    const tap = node('media-gesture');
    tap.setAttribute('type', 'tap');
    tap.setAttribute('action', 'togglePaused');

    const controls = node('media-controls');
    const content = node('media-controls-content', 'simulation-video-controls');

    const timeline = node('media-time-slider', 'simulation-video-timeline');
    timeline.setAttribute('label', 'Position');
    const track = node('media-slider-track');
    track.appendChild(node('media-slider-fill'));
    timeline.append(track, node('media-slider-thumb'));

    const row = node('media-controls-group', 'simulation-video-row');
    row.setAttribute('aria-label', 'Playback');

    const play = node('media-play-button', 'simulation-video-button simulation-video-play');
    play.append(icon(playIcon, 'show-paused'), icon(pauseIcon, 'show-playing'), icon(restartIcon, 'show-ended'));

    const back = node('media-seek-button', 'simulation-video-button simulation-video-back');
    back.setAttribute('seconds', String(-STEP));
    back.appendChild(icon(seekIcon));
    const forward = node('media-seek-button', 'simulation-video-button simulation-video-forward');
    forward.setAttribute('seconds', String(STEP));
    forward.appendChild(icon(seekIcon));

    // From the start, whether it is playing, paused or over.
    const replay = button('simulation-video-button simulation-video-replay', 'Play from the start', icon(restartIcon));
    replay.addEventListener('click', () => {
        video.currentTime = 0;
        void video.play().catch(() => undefined);
    });

    const time = node('media-time-group', 'simulation-video-time');
    const current = node('media-time');
    current.setAttribute('type', 'current');
    const duration = node('media-time');
    duration.setAttribute('type', 'duration');
    time.append(current, node('media-time-separator'), duration);

    const spacer = node('span', 'simulation-video-spacer');

    const rate = node('media-playback-rate-button', 'simulation-video-button simulation-video-rate');

    const fullscreen = button(
        'simulation-video-button simulation-video-fullscreen',
        'Full screen',
        icon(fullscreenEnterIcon, 'show-windowed'),
        icon(fullscreenExitIcon, 'show-fullscreen'),
    );

    row.append(play, back, forward, replay, time, spacer, rate, fullscreen);
    content.append(timeline, row);
    controls.appendChild(content);

    container.append(video, poster, tap, controls);
    for (const [keys, action, value] of [
        ['Space', 'togglePaused', undefined],
        ['k', 'togglePaused', undefined],
        ['ArrowLeft', 'seekStep', -STEP],
        ['ArrowRight', 'seekStep', STEP],
        ['j', 'seekStep', -STEP],
        ['l', 'seekStep', STEP],
        ['Shift+.', 'speedUp', undefined],
        ['Shift+,', 'speedDown', undefined],
        ['0-9', 'seekToPercent', undefined],
    ] as const) {
        const hotkey = node('media-hotkey');
        hotkey.setAttribute('keys', keys);
        hotkey.setAttribute('action', action);
        if (value !== undefined) {
            hotkey.setAttribute('value', String(value));
        }
        container.appendChild(hotkey);
    }
    player.appendChild(container);
    element.appendChild(player);

    // The player the shape of the video, once the video says what that is.
    video.addEventListener('loadedmetadata', () => {
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            element.style.setProperty('--simulation-video-aspect', String(video.videoWidth / video.videoHeight));
        }
    });

    // Full screen, ours rather than Video.js's (see the top of this file).
    let filling = false;
    const fill = (on: boolean) => {
        if (filling === on) {
            return;
        }
        filling = on;
        element.classList.toggle('simulation-video-filling', on);
        options.onFullscreen(on);
        showFullscreen();
    };
    const showFullscreen = () => {
        const on = filling || document.fullscreenElement === container;
        element.toggleAttribute('data-fullscreen', on);
        fullscreen.title = on ? 'Leave full screen' : 'Full screen';
        fullscreen.setAttribute('aria-label', fullscreen.title);
    };
    const toggleFullscreen = () => {
        if (document.fullscreenElement === container) {
            void document.exitFullscreen().catch(() => undefined);
        } else if (filling) {
            fill(false);
        } else if (document.fullscreenEnabled) {
            void container.requestFullscreen().catch(() => fill(true));
        } else {
            fill(true);
        }
    };
    fullscreen.addEventListener('click', toggleFullscreen);
    video.addEventListener('dblclick', toggleFullscreen);
    document.addEventListener('fullscreenchange', showFullscreen);
    // 'f' toggles full screen while the player has the focus, as on every
    // player; Escape leaves it wherever the focus is.
    container.addEventListener('keydown', (event: KeyboardEvent) => {
        if ((event.key === 'f' || event.key === 'F') && !event.ctrlKey && !event.metaKey && !event.altKey) {
            event.preventDefault();
            toggleFullscreen();
        }
    });
    const escape = (event: KeyboardEvent) => {
        if (event.key === 'Escape' && filling) {
            fill(false);
        }
    };
    document.addEventListener('keydown', escape);
    showFullscreen();

    let disposed = false;
    void drawStill(still, video).then((picture) => {
        if (!disposed && picture !== undefined) {
            player.setAttribute('poster', picture);
        }
    });

    return {
        element,
        dispose: () => {
            disposed = true;
            if (document.fullscreenElement === container) {
                void document.exitFullscreen().catch(() => undefined);
            }
            fill(false);
            document.removeEventListener('fullscreenchange', showFullscreen);
            document.removeEventListener('keydown', escape);
            // What it plays from now, which is not 'url' where Media Source
            // Extensions refused the file (see 'feed').
            const playing = video.src;
            video.pause();
            video.removeAttribute('src');
            video.load();
            URL.revokeObjectURL(url);
            if (playing !== url && playing.startsWith('blob:')) {
                URL.revokeObjectURL(playing);
            }
        },
    };
}

/**
 * The run's two pictures as one, the shape of the video: before on the left,
 * after on the right, an arrow between them, each named over it. Undefined
 * when there are none to draw.
 */
async function drawStill(still: SimulationStill, video: HTMLVideoElement): Promise<string | undefined> {
    if (still.before === undefined && still.after === undefined) {
        return undefined;
    }
    const [before, after, size] = await Promise.all([picture(still.before), picture(still.after), videoSize(video)]);
    const canvas = document.createElement('canvas');
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext('2d');
    if (context === null) {
        return undefined;
    }
    const { width, height } = size;
    context.fillStyle = STILL_BACKGROUND;
    context.fillRect(0, 0, width, height);

    // The names over the pictures rather than under them: the foot of the
    // picture is where the controls are.
    const margin = Math.round(height * 0.05);
    const caption = Math.round(height * 0.08);
    const foot = Math.round(height * 0.14);
    const gap = Math.round(width * 0.1);
    const top = margin + caption;
    const box = { width: (width - 2 * margin - gap) / 2, height: height - top - foot };
    context.font = `${Math.round(caption * 0.55)}px system-ui, -apple-system, 'Segoe UI', sans-serif`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    for (const [image, left, label] of [
        [before, margin, 'Before'],
        [after, margin + box.width + gap, 'After'],
    ] as const) {
        if (image !== undefined) {
            const scale = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
            const drawnWidth = image.naturalWidth * scale;
            const drawnHeight = image.naturalHeight * scale;
            context.drawImage(
                image,
                left + (box.width - drawnWidth) / 2,
                top + (box.height - drawnHeight) / 2,
                drawnWidth,
                drawnHeight,
            );
        }
        context.fillStyle = STILL_INK;
        context.fillText(
            image === undefined ? `${label}: no picture` : label,
            left + box.width / 2,
            margin + caption / 2,
        );
    }

    // The arrow: a shaft and a head, in the gap and level with the pictures' middle.
    const middle = top + box.height / 2;
    const start = margin + box.width + gap * 0.2;
    const end = margin + box.width + gap * 0.8;
    const head = gap * 0.22;
    context.strokeStyle = STILL_INK;
    context.fillStyle = STILL_INK;
    context.lineWidth = Math.max(2, height * 0.008);
    context.lineCap = 'round';
    context.beginPath();
    context.moveTo(start, middle);
    context.lineTo(end - head * 0.6, middle);
    context.stroke();
    context.beginPath();
    context.moveTo(end, middle);
    context.lineTo(end - head, middle - head * 0.6);
    context.lineTo(end - head, middle + head * 0.6);
    context.closePath();
    context.fill();
    return canvas.toDataURL('image/png');
}

/** A picture of a run, decoded; undefined for none, or one that will not decode. */
function picture(image: SimulationImage | undefined): Promise<HTMLImageElement | undefined> {
    if (image === undefined) {
        return Promise.resolve(undefined);
    }
    // A Blob URL of its own, let go of once the picture is decoded: it is
    // drawn into the still and not shown itself.
    const url = URL.createObjectURL(new Blob([arrayBacked(image.content)], { type: mimeType(image.extension) }));
    return new Promise((resolve) => {
        const decoded = new Image();
        decoded.onload = () => {
            URL.revokeObjectURL(url);
            resolve(decoded);
        };
        decoded.onerror = () => {
            URL.revokeObjectURL(url);
            resolve(undefined);
        };
        decoded.src = url;
    });
}

/**
 * Give 'video' the file's bytes to play, and return the URL it plays them from.
 *
 * Through Media Source Extensions where the browser has them, the bytes handed
 * to the video in one piece. A Visual Studio Code webview is why: it plays no
 * 'blob:' URL of a file at all -- "FFmpegDemuxer: open context failed", for a
 * WebM any browser plays -- while a 'MediaSource' it is fed is played, sought
 * in and timed like any other. Where there is none, or it refuses the file, the
 * file's own 'blob:' URL is played instead, which is what a browser does well.
 */
function feed(video: HTMLVideoElement, content: Uint8Array, extension: string): string {
    const data = arrayBacked(content);
    const type = mimeType(extension);
    const codecs = type === 'video/webm' ? WEBM_SOURCE_TYPES : undefined;
    const supported =
        typeof MediaSource !== 'undefined' ? codecs?.find((t) => MediaSource.isTypeSupported(t)) : undefined;
    if (supported === undefined) {
        const url = URL.createObjectURL(new Blob([data], { type }));
        video.src = url;
        return url;
    }
    const source = new MediaSource();
    const url = URL.createObjectURL(source);
    const fallBack = () => {
        URL.revokeObjectURL(video.src);
        video.src = URL.createObjectURL(new Blob([data], { type }));
    };
    source.addEventListener(
        'sourceopen',
        () => {
            try {
                const buffer = source.addSourceBuffer(supported);
                buffer.addEventListener(
                    'updateend',
                    () => {
                        if (source.readyState === 'open') {
                            source.endOfStream();
                        }
                    },
                    { once: true },
                );
                buffer.addEventListener('error', fallBack, { once: true });
                buffer.appendBuffer(data);
            } catch {
                fallBack();
            }
        },
        { once: true },
    );
    video.src = url;
    return url;
}

/**
 * What a WebM video is declared to Media Source Extensions as, in the order
 * tried: the plugins encode VP9, and the rest are what else WebM commonly holds.
 */
const WEBM_SOURCE_TYPES = [
    'video/webm; codecs="vp9"',
    'video/webm; codecs="vp8"',
    'video/webm; codecs="av01.0.08M.08"',
];

/** The size of the video, once it says; HD if it never does. */
function videoSize(video: HTMLVideoElement): Promise<{ width: number; height: number }> {
    const known = () =>
        video.videoWidth > 0 && video.videoHeight > 0
            ? { width: video.videoWidth, height: video.videoHeight }
            : STILL_SIZE;
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        return Promise.resolve(known());
    }
    if (video.error !== null) {
        // It will say nothing more, having failed already.
        return Promise.resolve(STILL_SIZE);
    }
    return new Promise((resolve) => {
        video.addEventListener('loadedmetadata', () => resolve(known()), { once: true });
        video.addEventListener('error', () => resolve(STILL_SIZE), { once: true });
    });
}

function node(tag: string, className?: string): HTMLElement {
    const created = document.createElement(tag);
    if (className) {
        created.className = className;
    }
    return created;
}

function button(className: string, label: string, ...icons: HTMLElement[]): HTMLButtonElement {
    const created = document.createElement('button');
    created.type = 'button';
    created.className = className;
    created.title = label;
    created.setAttribute('aria-label', label);
    created.append(...icons);
    return created;
}

/** One of Video.js's icons, as the SVG it ships as; Video.js's own icon element loads its sets lazily, which the panel's CSP does not allow. */
function icon(svg: string, className?: string): HTMLElement {
    const holder = document.createElement('span');
    holder.className = className ? `simulation-video-icon ${className}` : 'simulation-video-icon';
    holder.setAttribute('aria-hidden', 'true');
    holder.innerHTML = svg;
    return holder;
}

/** Bytes the host posted, typed as what a Blob and a SourceBuffer take: a structured clone is never shared memory. */
function arrayBacked(bytes: Uint8Array): Uint8Array<ArrayBuffer> {
    return bytes as Uint8Array<ArrayBuffer>;
}

function mimeType(extension: string): string {
    switch ((extension || '').toLowerCase()) {
        case 'webm':
            return 'video/webm';
        case 'mp4':
            return 'video/mp4';
        case 'jpg':
        case 'jpeg':
            return 'image/jpeg';
        case 'svg':
            return 'image/svg+xml';
        default:
            return 'image/png';
    }
}
