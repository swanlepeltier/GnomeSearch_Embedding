// Async D-Bus client for the Python backend.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {DBUS_BUS_NAME, DBUS_OBJECT_PATH} from './utils.js';

const DBUS_IFACE = 'org.gnome.EmbeddingSearch';

export class DbusClient {
    constructor() {
        this._proxy = null;
        this._pending = null;
    }

    // Lazily create the proxy. Rejects if the backend is unreachable so callers
    // can simply show no results.
    _getProxy() {
        if (this._proxy)
            return Promise.resolve(this._proxy);
        if (this._pending)
            return this._pending;

        this._pending = new Promise((resolve, reject) => {
            Gio.DBusProxy.new_for_bus(
                Gio.BusType.SESSION,
                // DO_NOT_LOAD_PROPERTIES keeps proxy creation cheap while still
                // allowing the systemd unit to be D-Bus-activated on first call.
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                null,
                DBUS_BUS_NAME,
                DBUS_OBJECT_PATH,
                DBUS_IFACE,
                null,
                (source, result) => {
                    try {
                        this._proxy = Gio.DBusProxy.new_for_bus_finish(result);
                        resolve(this._proxy);
                    } catch (error) {
                        this._pending = null;
                        reject(error);
                    }
                });
        });
        return this._pending;
    }

    async _callAsync(method, parameters, timeout) {
        const proxy = await this._getProxy();
        return new Promise((resolve, reject) => {
            proxy.call(
                method,
                parameters,
                Gio.DBusCallFlags.NONE,
                timeout,
                null,
                (source, result) => {
                    try {
                        resolve(source.call_finish(result));
                    } catch (error) {
                        reject(error);
                    }
                });
        });
    }

    async search(query, maxResults) {
        const reply = await this._callAsync(
            'Search', new GLib.Variant('(su)', [query, maxResults]), 5000);
        const payload = JSON.parse(reply.deep_unpack()[0]);
        if (Array.isArray(payload))
            return payload;              // plain array (legacy)
        return payload.results ?? [];    // {"results": [...], "error": ...}
    }

    async getStatus() {
        const reply = await this._callAsync('GetStatus', null, 3000);
        return JSON.parse(reply.deep_unpack()[0]);
    }

    async reindex(full = false) {
        await this._callAsync('Reindex', new GLib.Variant('(b)', [Boolean(full)]), 3000);
    }
}
