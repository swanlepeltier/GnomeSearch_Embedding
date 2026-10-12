// Shared helpers for the search provider and the preview widget.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

// ``Gio.DesktopAppInfo`` moved to the platform-specific ``GioUnix`` namespace in
// GLib 2.80 (GNOME 50). Prefer the new location and fall back to the deprecated
// accessor so the extension keeps working on GNOME 45-49.
let DesktopAppInfo = null;
try {
    const {default: GioUnix} = await import('gi://GioUnix');
    DesktopAppInfo = GioUnix?.DesktopAppInfo ?? null;
} catch {
    // GioUnix is unavailable on GNOME < 50.
}
if (!DesktopAppInfo)
    DesktopAppInfo = Gio.DesktopAppInfo;

export const DBUS_BUS_NAME = 'org.gnome.EmbeddingSearch';
export const DBUS_OBJECT_PATH = '/org/gnome/EmbeddingSearch';

// Icon name used when a file has no thumbnail (per media kind).
const FALLBACK_ICONS = {
    video: 'video-x-generic-symbolic',
    image: 'image-x-generic-symbolic',
    audio: 'audio-x-generic-symbolic',
    text: 'text-x-generic-symbolic',
};

export function formatTimestamp(seconds) {
    if (seconds === null || seconds === undefined)
        return null;
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0)
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    return `${minutes}:${String(secs).padStart(2, '0')}`;
}

export function scorePercent(score) {
    const clamped = Math.max(0, Math.min(1, Number(score) || 0));
    return Math.round(clamped * 100);
}

// A themed icon describing the *type* of a file (the "language logo"): e.g.
// ``text-x-python`` for a ``.py`` file, ``application-pdf`` for a PDF, ...
function mimeIcon(path) {
    try {
        const [contentType] = Gio.content_type_guess(path, null);
        if (contentType)
            return Gio.content_type_get_icon(contentType);
    } catch (error) {
        logError(error, 'embedding-search: could not resolve a mime icon');
    }
    return null;
}

// Build the leading preview of a result: a real raster thumbnail for images and
// videos, otherwise a themed icon for the file's type. Never hand a non-image
// path to ``Gio.FileIcon``: it renders as an empty box (that was the bug making
// text results show blank squares).
export function createThumbnailIcon(meta, size) {
    const kind = meta.kind ?? 'text';
    const thumbnail = meta.thumbnail;

    if (thumbnail && (kind === 'image' || kind === 'video')) {
        const file = Gio.File.new_for_path(thumbnail);
        if (file.query_exists(null)) {
            return makeIcon({
                style_class: 'embedding-result-thumb-image',
                gicon: new Gio.FileIcon({file}),
                icon_size: size,
            });
        }
    }

    const iconSize = Math.max(16, Math.round(size * 0.55));
    const gicon = mimeIcon(meta.path);
    if (gicon) {
        return makeIcon({
            style_class: 'embedding-result-thumb-icon',
            gicon,
            icon_size: iconSize,
        });
    }
    return makeIcon({
        style_class: 'embedding-result-thumb-icon',
        icon_name: FALLBACK_ICONS[kind] ?? FALLBACK_ICONS.text,
        icon_size: iconSize,
    });
}

// St.Icon centred inside its (fixed-size) St.Bin container: ClutterBinLayout
// would otherwise stretch the icon to fill the whole box, blowing up the small
// file-type icons.
function makeIcon(params) {
    return new St.Icon({
        x_align: Clutter.ActorAlign.CENTER,
        y_align: Clutter.ActorAlign.CENTER,
        ...params,
    });
}

// Minimal GAppInfo so GNOME Shell renders our provider as a vertical *list*
// (it only builds ``ListSearchResults`` when ``provider.appInfo`` is set) and
// shows a proper section header. ``get_id()`` is null, so the header is made
// non-interactive by the caller.
export function createProviderAppInfo() {
    try {
        const keyfile = new GLib.KeyFile();
        keyfile.set_string('Desktop Entry', 'Type', 'Application');
        keyfile.set_string('Desktop Entry', 'Name', 'Semantic Embedding Search');
        keyfile.set_string('Desktop Entry', 'Icon', 'system-search-symbolic');
        keyfile.set_string('Desktop Entry', 'Exec', 'true');
        return DesktopAppInfo.new_from_keyfile(keyfile);
    } catch (error) {
        logError(error, 'embedding-search: could not build the provider app info');
        return null;
    }
}

// Players that understand a "start at" command-line flag.
const SEEK_PLAYERS = [
    {match: 'mpv', flag: (t) => `--start=${t}`},
    {match: 'vlc', flag: (t) => `--start-time=${t}`},
    {match: 'celluloid', flag: (t) => `--start-time=${t}`},
    {match: 'smplayer', flag: (t) => `-start ${t}`},
    {match: 'totem', flag: (t) => `--start-time=${t}`},
];

// Try to open ``meta.path`` at ``meta.timestamp`` using the user's default
// application. If the default player supports seeking we pass the right flag,
// otherwise the file is simply opened normally (never assume mpv/vlc is present).
export function openResult(meta) {
    const file = Gio.File.new_for_path(meta.path);
    const uri = file.get_uri();

    if (meta.timestamp === null || meta.timestamp === undefined ||
        (meta.kind !== 'video' && meta.kind !== 'audio')) {
        Gio.AppInfo.launch_default_for_uri(uri, null);
        return;
    }

    const [contentType] = Gio.content_type_guess(meta.path, null);
    const appInfo = Gio.AppInfo.get_default_for_type(contentType, false);
    const start = Math.max(0, Math.floor(meta.timestamp));

    if (appInfo) {
        const executable = (appInfo.get_executable() || '').split('/').pop().toLowerCase();
        const player = SEEK_PLAYERS.find(p => executable.includes(p.match));
        if (player) {
            const command = `${executable} ${player.flag(start)} ${GLib.shell_quote(meta.path)}`;
            try {
                GLib.spawn_command_line_async(command);
                return;
            } catch (error) {
                logError(error, 'embedding-search: failed to spawn player');
            }
        }
    }

    // Fallback: open with whatever the user has configured as the default app.
    Gio.AppInfo.launch_default_for_uri(uri, null);
}
