// Shared helpers for the search provider and the preview widget.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

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

// Build a St.Icon from a file path, falling back to a themed icon.
export function createFileIcon(path, size, kind = 'text') {
    if (path) {
        const file = Gio.File.new_for_path(path);
        if (file.query_exists(null)) {
            return new St.Icon({
                gicon: new Gio.FileIcon({file}),
                icon_size: size,
            });
        }
    }
    return new St.Icon({
        icon_name: FALLBACK_ICONS[kind] ?? FALLBACK_ICONS.text,
        icon_size: size,
    });
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
