// Extension entry point: register/unregister the search provider.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {EmbeddingSearchProvider} from './searchProvider.js';
import {createProviderAppInfo} from './utils.js';

export default class EmbeddingSearchExtension extends Extension {
    enable() {
        this._provider = new EmbeddingSearchProvider();
        const controller = Main.overview.searchController;
        controller.addProvider(this._provider);
        this._useListView(controller);
        this._moveProviderToTop(controller);
    }

    // GNOME builds a *horizontal grid* for providers without an ``appInfo``
    // (see SearchResultsView._ensureProviderDisplay). We register first without
    // one — so the parental-controls check in _registerProvider() can never
    // silently drop us — then attach an appInfo and rebuild the display so the
    // results become a vertical list with our rich rows.
    _useListView(controller) {
        const view = controller?._searchResults;
        if (!view?._content || typeof view._ensureProviderDisplay !== 'function')
            return;
        try {
            if (this._provider.display) {
                this._provider.display.destroy();
                this._provider.display = null;
            }
            this._provider.appInfo = createProviderAppInfo();
            view._ensureProviderDisplay(this._provider);

            // The section header is decorative: we are not a launchable app.
            const header = this._provider.display?.providerInfo;
            if (header) {
                header.reactive = false;
                header.can_focus = false;
            }
        } catch (error) {
            logError(error, 'embedding-search: could not switch to the list layout');
        }
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
