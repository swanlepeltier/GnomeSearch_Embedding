// GNOME Shell search provider backed by the Python D-Bus service.
import {DbusClient} from './dbusClient.js';
import {createResultWidget} from './previewWidget.js';
import {createFileIcon, openResult} from './utils.js';

const MAX_RESULTS = 8;
const MIN_QUERY_LENGTH = 2;
const FALLBACK_ICON_SIZE = 48;

export class EmbeddingSearchProvider {
    constructor() {
        // Required provider properties.
        this.id = 'embedding-search';
        this.isRemoteProvider = false;
        this.canLaunchSearch = false;
        this.searchInProgress = false;

        this._client = new DbusClient();
        // id -> meta, so activateResult()/getResultMetas() can resolve results.
        this._metas = new Map();
    }

    // -- SearchProvider interface --------------------------------------------
    async getInitialResultSet(terms, cancellable) {
        void cancellable;
        const query = terms.join(' ').trim();
        if (query.length < MIN_QUERY_LENGTH)
            return [];

        let results;
        try {
            results = await this._client.search(query, MAX_RESULTS);
        } catch (error) {
            logError(error, 'embedding-search: search unavailable');
            return [];
        }

        const ids = [];
        for (const result of results) {
            const id = String(result.id);
            this._metas.set(id, this._toMeta(result));
            ids.push(id);
        }
        return ids;
    }

    async getSubsearchResultSet(previousResults, terms, cancellable) {
        // A semantic backend has no notion of "refining" a previous result set:
        // re-running the query is the only correct behaviour. Intersecting with
        // the previous ids made every forward keystroke return [] (the first
        // keystroke is below MIN_QUERY_LENGTH, so it poisons the chain), which
        // is why results only appeared when the user deleted the last character.
        void previousResults;
        return this.getInitialResultSet(terms, cancellable);
    }

    getResultMetas(ids, cancellable) {
        void cancellable;
        const metas = ids
            .map(id => this._metas.get(id))
            .filter(meta => meta !== undefined);
        return Promise.resolve(metas);
    }

    filterResults(results, maxNumber) {
        return results.slice(0, maxNumber);
    }

    activateResult(id, terms) {
        void terms;
        const meta = this._metas.get(id);
        if (meta)
            openResult(meta);
    }

    launchSearch(terms) {
        // The backend is a service, not an application: nothing to launch.
        void terms;
    }

    createResultObject(meta) {
        return createResultWidget(this, meta);
    }

    // -- helpers -------------------------------------------------------------
    _toMeta(result) {
        const kind = result.kind ?? 'text';
        const thumbnail = result.thumbnail ?? null;
        const path = result.path;
        return {
            id: String(result.id),
            name: result.name ?? 'Unknown',
            description: result.description ?? '',
            kind,
            path,
            path_display: result.path_display ?? path,
            timestamp: result.timestamp ?? null,
            duration: result.duration ?? null,
            score: result.score ?? 0,
            thumbnail,
            snippet: result.snippet ?? null,
            // Used by the shell when createResultObject() is not available.
            createIcon: size =>
                createFileIcon(thumbnail || path, size ?? FALLBACK_ICON_SIZE, kind),
        };
    }
}
