// Rich result widget used through SearchProvider.createResultObject().
//
// Layout:
//   [ large thumbnail ]  filename
//                        ~/path/to/file
//                        [score]  [at 0:42]
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {createFileIcon, formatTimestamp, scorePercent} from './utils.js';

const THUMBNAIL_SIZE = 96;

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

        const content = new St.BoxLayout({
            style_class: 'embedding-result-content',
            x_expand: true,
            y_expand: true,
        });
        this.set_child(content);

        // Large thumbnail (falls back to a themed icon).
        const thumbnail = createFileIcon(
            meta.thumbnail || meta.path, THUMBNAIL_SIZE, meta.kind);
        thumbnail.add_style_class_name('embedding-result-thumbnail');
        content.add_child(thumbnail);

        // Text column.
        const info = new St.BoxLayout({
            style_class: 'embedding-result-info',
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        content.add_child(info);

        info.add_child(new St.Label({
            style_class: 'embedding-result-title',
            text: meta.name,
            x_align: Clutter.ActorAlign.START,
        }));

        info.add_child(new St.Label({
            style_class: 'embedding-result-path',
            text: meta.path_display ?? meta.path,
            x_align: Clutter.ActorAlign.START,
        }));

        const badges = new St.BoxLayout({
            style_class: 'embedding-result-badges',
            x_align: Clutter.ActorAlign.START,
        });
        info.add_child(badges);

        badges.add_child(new St.Label({
            style_class: 'embedding-score-badge',
            text: `${scorePercent(meta.score)}%`,
        }));

        const timestamp = formatTimestamp(meta.timestamp);
        if (timestamp) {
            badges.add_child(new St.Label({
                style_class: 'embedding-timestamp',
                text: `at ${timestamp}`,
            }));
        }

        this.connect('clicked', () => {
            this._provider.activateResult(this._meta.id, []);
            Main.overview.toggle();
        });
    }
});

export function createResultWidget(provider, meta) {
    return new PreviewResultWidget(provider, meta);
}
