// Extension entry point: register/unregister the search provider.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {EmbeddingSearchProvider} from './searchProvider.js';

export default class EmbeddingSearchExtension extends Extension {
    enable() {
        this._provider = new EmbeddingSearchProvider();
        Main.overview.searchController.addProvider(this._provider);
    }

    disable() {
        if (this._provider) {
            Main.overview.searchController.removeProvider(this._provider);
            this._provider = null;
        }
    }
}
