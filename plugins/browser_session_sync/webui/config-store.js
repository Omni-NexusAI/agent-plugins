import { createStore } from "/js/AlpineStore.js";
import { fetchApi } from "/js/api.js";

const DEFAULT_CONFIG = {
    auto_restore: true,
    auto_save: true,
    session_scope: "global",
    delete_on_chat_remove: true,
    max_auto_restore_tabs: 0,
    max_saved_sessions: 500,
    max_cache_mb: 1024,
};

const CONFIG_KEYS = Object.keys(DEFAULT_CONFIG);

function normalizeConfig(config = {}) {
    const next = { ...DEFAULT_CONFIG, ...config };
    delete next.enabled;
    delete next.allow_global_fallback;
    next.auto_restore = Boolean(next.auto_restore);
    next.auto_save = Boolean(next.auto_save);
    next.session_scope = next.session_scope === "chat" ? "chat" : "global";
    next.delete_on_chat_remove = Boolean(next.delete_on_chat_remove);
    next.max_auto_restore_tabs = Number(next.max_auto_restore_tabs) || 0;
    next.max_saved_sessions = Number(next.max_saved_sessions) || DEFAULT_CONFIG.max_saved_sessions;
    next.max_cache_mb = Number(next.max_cache_mb) || DEFAULT_CONFIG.max_cache_mb;
    return next;
}

function cloneConfig(config) {
    return normalizeConfig(JSON.parse(JSON.stringify(config || DEFAULT_CONFIG)));
}

const model = {
    loading: false,
    sessions: [],
    stats: null,
    error: "",
    deleting: null,
    expanded: {},
    lastActionResult: "",
    config: cloneConfig(DEFAULT_CONFIG),
    draftConfig: cloneConfig(DEFAULT_CONFIG),
    configSaving: false,

    async init() {
        await this.loadConfig();
        await this.loadSessions({ applyConfig: false });
    },

    async request(action, payload = {}) {
        const response = await fetchApi("/plugins/browser_session_sync/sessions_list", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, ...payload })
        });
        return await response.json();
    },

    applyConfig(config, { updateDraft = true } = {}) {
        this.config = normalizeConfig(config);
        if (updateDraft) {
            this.draftConfig = cloneConfig(this.config);
        }
    },

    hasUnsavedChanges() {
        return CONFIG_KEYS.some((key) => this.config[key] !== this.draftConfig[key]);
    },

    resetDraft() {
        this.draftConfig = cloneConfig(this.config);
        this.error = "";
        this.lastActionResult = "Changes reset";
    },

    async loadConfig() {
        try {
            const data = await this.request("get_config");
            if (data.ok !== false && data.config) {
                this.applyConfig(data.config);
            }
        } catch (e) {
            this.error = e.message || "Failed to load settings";
        }
    },

    async saveConfig() {
        this.configSaving = true;
        this.error = "";
        this.lastActionResult = "";
        const draft = cloneConfig(this.draftConfig);
        try {
            const data = await this.request("save_config", { config: draft });
            if (data.ok !== false && data.config) {
                this.applyConfig(data.config);
                this.lastActionResult = "Settings saved";
                await this.loadSessions({ applyConfig: false });
            } else {
                this.draftConfig = draft;
                this.error = data.error || "Failed to save settings";
            }
        } catch (e) {
            this.draftConfig = draft;
            this.error = e.message || "Failed to save settings";
        } finally {
            this.configSaving = false;
        }
    },

    async loadSessions({ applyConfig = true } = {}) {
        this.loading = true;
        this.error = "";
        try {
            const data = await this.request("list");
            if (data.ok !== false) {
                this.sessions = data.sessions || [];
                this.stats = data.stats || null;
                if (applyConfig && data.config) {
                    this.applyConfig(data.config, { updateDraft: !this.hasUnsavedChanges() });
                }
            } else {
                this.error = data.error || "Failed to load sessions";
            }
        } catch (e) {
            this.error = e.message || "Failed to load sessions";
        } finally {
            this.loading = false;
        }
    },

    async deleteSession(filename) {
        this.deleting = filename;
        this.error = "";
        try {
            const data = await this.request("delete", { filename });
            if (data.ok !== false) {
                this.lastActionResult = `Deleted ${filename}`;
                await this.loadSessions({ applyConfig: false });
            } else {
                this.error = data.error || "Delete failed";
            }
        } catch (e) {
            this.error = e.message || "Delete failed";
        } finally {
            this.deleting = null;
        }
    },

    async deleteAll() {
        if (!confirm("Delete all saved browser session snapshots?")) return;
        this.deleting = "all";
        this.error = "";
        try {
            const data = await this.request("delete_all");
            if (data.ok !== false) {
                this.lastActionResult = `Cleared ${data.deleted || 0} sessions`;
                await this.loadSessions({ applyConfig: false });
            } else {
                this.error = data.error || "Clear all failed";
            }
        } catch (e) {
            this.error = e.message || "Clear all failed";
        } finally {
            this.deleting = null;
        }
    },

    toggleDetails(name) {
        this.expanded[name] = !this.expanded[name];
    },

    getHostname(url) {
        if (!url) return "(empty)";
        try {
            return new URL(url).hostname;
        } catch {
            return url.substring(0, 80);
        }
    },

    restoreLimitLabel() {
        return this.draftConfig.max_auto_restore_tabs > 0
            ? `${this.draftConfig.max_auto_restore_tabs} tabs`
            : "Native browser limit";
    },

    storageLabel() {
        const size = this.stats?.total_size_str || "0 B";
        return `${size} / ${this.config.max_cache_mb} MB`;
    }
};

export const store = createStore("browserSessionSync", model);
