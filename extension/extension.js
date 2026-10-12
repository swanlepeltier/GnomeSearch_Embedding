// Extension entry point: register/unregister the search provider.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {EmbeddingSearchProvider} from './searchProvider.js';

export default class EmbeddingSearchExtension extends Extension {
    enable() {
        this._provider = new EmbeddingSearchProvider();
        const controller = Main.overview.searchController;
        controller.addProvider(this._provider);
        this._moveProviderToTop(controller);
    }

    // GNOME stacks result sections in the order providers were registered, and
    // there is no public API for priority. Move ours to the front so the
    // semantic results appear at the top (and become the default Enter target).
    _moveProviderToTop(controller) {
        try {
            const view = controller?._searchResults;
            if (!view?._providers || !view?._content)
                return;
            const index = view._providers.indexOf(this._provider);
            if (index > 0) {
                view._providers.splice(index, 1);
                view._providers.unshift(this._provider);
            }
            if (this._provider.display)
                view._content.set_child_at_index(this._provider.display, 0);
        } catch (error) {
            logError(error, 'embedding-search: could not move provider to top');
        }
    }

    disable() {
        if (this._provider) {
            Main.overview.searchController.removeProvider(this._provider);
            this._provider = null;
        }
    }
}
