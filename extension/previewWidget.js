// Rich result widget used through SearchProvider.createResultObject().
//
// The best match (rank 0) is rendered as a large "hero" card; the remaining
// results are compact rows. Both share the same layout:
//
//   [ thumbnail ]  filename.ext                          [ 92% ]
//                  Video • 1:23 • frame at 0:42
//                  ~/Videos/project/clip.mp4
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {createThumbnailIcon, formatTimestamp, scorePercent} from './utils.js';

// Leading preview icon size (px) inside the fixed-size thumb box (see CSS).
const HERO_ICON_SIZE = 104;
const COMPACT_ICON_SIZE = 48;

export const PreviewResultWidget = GObject.registerClass(
class PreviewResultWidget extends St.Button {
    _init(provider, meta) {
        super._init({
            style_class: 'embedding-search-result',
            reactive: true,
            track_hover: true,
            can_focus: true,
            x_expand: true,
        });

        this._provider = provider;
        this._meta = meta;

        const isHero = (meta.rank ?? 0) === 0;
        this.add_style_class_name(
            isHero ? 'embedding-result-hero' : 'embedding-result-compact');

        const row = new St.BoxLayout({
            style_class: 'embedding-result-content',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.set_child(row);

        // Leading thumbnail (image/video) or file-type icon.
        const thumb = new St.Bin({
            style_class: 'embedding-result-thumb',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        thumb.add_style_class_name(isHero
            ? 'embedding-result-thumb-hero'
            : 'embedding-result-thumb-compact');
        thumb.set_child(createThumbnailIcon(
            meta, isHero ? HERO_ICON_SIZE : COMPACT_ICON_SIZE));
        row.add_child(thumb);

        // Title + description + path.
        const info = new St.BoxLayout({
            style_class: 'embedding-result-info',
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        row.add_child(info);

        info.add_child(this._makeLabel(meta.name, 'embedding-result-title'));

        const description = (meta.description ?? '').trim() ||
            (meta.snippet ? String(meta.snippet).replace(/\s+/g, ' ').trim() : '');
        if (description)
            info.add_child(this._makeLabel(description, 'embedding-result-description'));

        info.add_child(this._makeLabel(
            meta.path_display ?? meta.path, 'embedding-result-path'));

        // Score (and, for videos, the matching timestamp) on the right.
        const side = new St.BoxLayout({
            style_class: 'embedding-result-side',
            orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.CENTER,
        });
        row.add_child(side);

        side.add_child(new St.Label({
            style_class: 'embedding-score-badge',
            text: `${scorePercent(meta.score)}%`,
            x_align: Clutter.ActorAlign.END,
        }));

        const timestamp = formatTimestamp(meta.timestamp);
        if (timestamp) {
            side.add_child(new St.Label({
                style_class: 'embedding-timestamp',
                text: timestamp,
                x_align: Clutter.ActorAlign.END,
            }));
        }

        this.connect('clicked', () => {
            this._provider.activateResult(this._meta.id, []);
            Main.overview.toggle();
        });
    }

    _makeLabel(text, styleClass) {
        const label = new St.Label({
            style_class: styleClass,
            text: text ?? '',
            x_align: Clutter.ActorAlign.START,
            x_expand: true,
        });
        label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        return label;
    }
});

export function createResultWidget(provider, meta) {
    return new PreviewResultWidget(provider, meta);
}
