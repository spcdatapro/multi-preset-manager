import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { showConfirmDialog } from "/js/confirmDialog.js";
import * as notifications from "/components/notifications/notification-store.js";
import { store as modelConfigStore } from "/plugins/_model_config/webui/model-config-store.js";

const PLUGIN = "multi_preset_manager";
const TITLE = "Multi-Preset Manager";
const MAX_LISTED = 8;
const MAX_VALUE_LENGTH = 140;
const SLOT_ORDER = ["chat", "utility", "embedding", "vision"];
const DEFAULT_NAME = "Default";

const api = (handler, data) => callJsonApi(`/plugins/${PLUGIN}/${handler}`, data);

function message(error, fallback) {
  const text = String(error?.message || error || "").trim();
  return (text || fallback).slice(0, 300);
}

const NORMAL = notifications.NotificationPriority.NORMAL;

// Toasts and confirm dialogs render their message as HTML (x-html / innerHTML): escape anything
// that comes from presets or from the server (names, error texts).
const esc = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const toastError = (text) => notifications.toastFrontendError(esc(text), TITLE, 6, PLUGIN, NORMAL, true);
const toastSuccess = (text) => notifications.toastFrontendSuccess(esc(text), TITLE, 4, PLUGIN, NORMAL, true);
const toastWarning = (text) => notifications.toastFrontendWarning(esc(text), TITLE, 8, PLUGIN, NORMAL, true);

const GROUP_HINTS = {
  model: "Provider and model name. If the provider changes, the API base and extra parameters are cleared unless you copy them too.",
  kwargs: "Provider-specific parameters such as thinking or temperature.",
  slot: "The whole sidecar model. Removed from the targets if the source has none.",
};

const KWARGS_TEXT = {
  merge: "merge: parameters of the source are added or overwritten; other parameters in the targets are kept",
  replace: "replace: the targets end up with exactly the parameters of the source",
};

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

const model = {
  tab: "copy", // "copy" | "duplicate" | "history"
  loading: false,
  presets: [],
  groupCatalog: [],
  slotBlocks: [],
  slotLabels: {},
  copy: { source: "", groups: {}, kwargsMode: "merge", targets: {}, preview: null, previewing: false, busy: false },
  dup: { source: "", name: "", openAfter: true, busy: false },
  history: { items: [], max: 20, loading: false, busy: false },

  async onOpen() {
    await this.load();
  },

  cleanup() {},

  setTab(name) {
    this.tab = name;
    if (name === "history") this.loadBackups();
  },

  // ---------- Loading ----------

  async load() {
    this.loading = true;
    try {
      const response = await api("presets_overview", {});
      this.presets = response.presets || [];
      this.groupCatalog = response.groups || [];
      this.slotLabels = response.slots || {};
      this.history.max = response.max_backups || 20;
      this.buildSlotBlocks();
      this.reconcile();
    } catch (error) {
      toastError(message(error, "Could not load the presets."));
    } finally {
      this.loading = false;
    }
  },

  buildSlotBlocks() {
    this.slotBlocks = SLOT_ORDER.map((slot) => ({
      slot,
      label: this.slotLabels[slot] || slot,
      groups: this.groupCatalog.filter((g) => g.slot === slot),
    })).filter((block) => block.groups.length > 0);
  },

  presetNames() {
    return this.presets.map((p) => p.name);
  },

  firstUsable() {
    return this.presetNames().find((n) => n !== DEFAULT_NAME) || this.presetNames()[0] || "";
  },

  // Keeps what the user selected when the list reloads (after the native editor, after applying).
  reconcile() {
    const names = this.presetNames();
    if (!names.includes(this.copy.source)) this.copy.source = this.firstUsable();
    this.copy.groups = Object.fromEntries(this.groupCatalog.map((g) => [g.id, !!this.copy.groups[g.id]]));
    this.rebuildTargets();
    this.copy.preview = null;
    if (!names.includes(this.dup.source)) this.dup.source = this.firstUsable();
  },

  rebuildTargets() {
    this.copy.targets = Object.fromEntries(this.copyTargets().map((p) => [p.name, !!this.copy.targets[p.name]]));
  },

  slotLabel(slot) {
    return this.slotLabels[slot] || slot;
  },

  // ---------- Copy settings ----------

  copyTargets() {
    return this.presets.filter((p) => p.name !== this.copy.source);
  },

  selectedGroups() {
    return this.groupCatalog.filter((g) => this.copy.groups[g.id]);
  },

  selectedTargets() {
    return this.copyTargets().filter((p) => this.copy.targets[p.name]);
  },

  hasKwargsGroup() {
    return this.selectedGroups().some((g) => g.kind === "kwargs");
  },

  groupHint(group) {
    return GROUP_HINTS[group.kind] || "";
  },

  groupLabel(id) {
    const group = this.groupCatalog.find((g) => g.id === id);
    return group ? `${group.slot_label} · ${group.label}` : id;
  },

  slotAll(block) {
    return block.groups.every((g) => this.copy.groups[g.id]);
  },

  setSlot(block, value) {
    for (const group of block.groups) this.copy.groups[group.id] = value;
    this.invalidate();
  },

  setAllTargets(value) {
    for (const name of Object.keys(this.copy.targets)) this.copy.targets[name] = value && name !== DEFAULT_NAME;
    this.invalidate();
  },

  // Any change to the selection makes the preview (and its hash) stale.
  invalidate() {
    this.copy.preview = null;
  },

  onSourceChanged() {
    this.rebuildTargets();
    this.invalidate();
  },

  canPreview() {
    return (
      !this.copy.previewing && !this.copy.busy && !!this.copy.source &&
      this.selectedGroups().length > 0 && this.selectedTargets().length > 0
    );
  },

  copyPayload() {
    return {
      source: this.copy.source,
      targets: this.selectedTargets().map((p) => p.name),
      groups: this.selectedGroups().map((g) => g.id),
      kwargs_mode: this.copy.kwargsMode,
    };
  },

  async editSource() {
    if (!this.copy.source) return;
    try {
      await modelConfigStore.openPresetEditor(this.copy.source);
    } catch (error) {
      toastError(message(error, "Could not open the preset editor."));
    } finally {
      await this.load(); // the preset may have been edited, renamed or deleted
    }
  },

  async previewCopy() {
    if (!this.canPreview()) return;
    this.copy.previewing = true;
    try {
      this.copy.preview = await api("preview_copy", this.copyPayload());
    } catch (error) {
      this.copy.preview = null;
      toastError(message(error, "Could not preview the changes."));
    } finally {
      this.copy.previewing = false;
    }
  },

  changesBySlot(item) {
    return SLOT_ORDER.map((slot) => ({
      slot,
      label: this.slotLabel(slot),
      rows: item.changes.filter((c) => c.slot === slot),
    })).filter((block) => block.rows.length > 0);
  },

  fmt(value) {
    if (value === null || value === undefined || value === "") return "—";
    const text = typeof value === "object" ? JSON.stringify(value) : String(value);
    return text.length > MAX_VALUE_LENGTH ? `${text.slice(0, MAX_VALUE_LENGTH)}…` : text;
  },

  namesList(names) {
    return names.map((n) => `<li>${esc(n)}</li>`).join("");
  },

  confirmHtml() {
    const preview = this.copy.preview;
    const warnings = preview.warnings;
    const groups = this.selectedGroups().map((g) => `<li>${esc(this.groupLabel(g.id))}</li>`).join("");
    const kwargs = this.hasKwargsGroup() ? ` <em>(${esc(KWARGS_TEXT[this.copy.kwargsMode])})</em>` : "";
    const targets = this.selectedTargets().map((p) => p.name);
    const listed = this.namesList(targets.slice(0, MAX_LISTED));
    const more = targets.length > MAX_LISTED ? `<li>and ${targets.length - MAX_LISTED} more…</li>` : "";
    const extra = [];
    if (warnings.default_target) {
      extra.push("<p><strong>Default is a target:</strong> every preset that inherits from it changes too.</p>");
    }
    if (warnings.reindex_embedding.length) {
      extra.push(
        `<p><strong>The embedding model changes</strong> in ${esc(warnings.reindex_embedding.join(", "))}. ` +
        "The memory is re-indexed the next time it is used, which can take a while.</p>"
      );
    }
    return `
      <p>Copy from <strong>${esc(this.copy.source)}</strong>:</p>
      <ul>${groups}</ul>${kwargs}
      <p>To ${plural(targets.length, "preset")}:</p>
      <ul>${listed}${more}</ul>
      <p>${plural(preview.changes.length, "preset")} will change. You can undo this from the History tab.</p>
      ${extra.join("")}
      <p>Close the native preset editor before continuing; saving it afterwards would overwrite this change.</p>`;
  },

  async applyCopy() {
    const preview = this.copy.preview;
    if (!preview || this.copy.busy) return;
    if (preview.changes.length === 0) {
      toastWarning("Nothing would change.");
      return;
    }
    const confirmed = await showConfirmDialog({
      title: "Copy settings",
      message: this.confirmHtml(),
      type: "warning",
      confirmText: "Copy settings",
      cancelText: "Cancel",
    });
    if (!confirmed) return;

    this.copy.busy = true;
    try {
      const result = await api("copy_settings", { ...this.copyPayload(), hash: preview.hash });
      if (result.changed.length === 0) {
        toastWarning("Nothing needed to change.");
      } else {
        toastSuccess(`Updated ${plural(result.changed.length, "preset")}. You can undo it from the History tab.`);
        if (result.warnings?.reindex_embedding?.length) {
          toastWarning("The embedding model changed: the memory will be re-indexed the next time it is used.");
        }
      }
      await this.load();
      this.loadBackups(true);
    } catch (error) {
      toastError(message(error, "Could not copy the settings."));
      await this.load(); // a stale preview means the presets changed: start from what is there now
    } finally {
      this.copy.busy = false;
    }
  },

  // ---------- Duplicate ----------

  dupPlaceholder() {
    return this.dup.source ? `${this.dup.source} copy` : "New preset";
  },

  dupHint() {
    const name = this.dup.name.trim();
    if (!name) return "";
    if (this.presets.some((p) => p.name.toLowerCase() === name.toLowerCase())) {
      return `A preset named "${name}" already exists.`;
    }
    return "";
  },

  canDuplicate() {
    return !this.dup.busy && !!this.dup.source && !!this.dup.name.trim() && !this.dupHint();
  },

  async duplicate() {
    if (!this.canDuplicate()) return;
    this.dup.busy = true;
    try {
      const result = await api("duplicate_preset", { source: this.dup.source, name: this.dup.name.trim() });
      toastSuccess(`Preset "${result.name}" created. You can undo it from the History tab.`);
      const openAfter = this.dup.openAfter;
      this.dup.name = "";
      await this.load();
      this.loadBackups(true);
      if (openAfter) {
        await modelConfigStore.openPresetEditor(result.name);
        await this.load();
      }
    } catch (error) {
      toastError(message(error, "Could not duplicate the preset."));
    } finally {
      this.dup.busy = false;
    }
  },

  // ---------- History (backups and undo) ----------

  kindLabel(backup) {
    return backup.kind === "duplicate" ? "Duplicate" : "Copy settings";
  },

  describe(backup) {
    if (backup.kind === "duplicate") return `from ${backup.source}`;
    const bySlot = new Map();
    for (const id of backup.groups) {
      const group = this.groupCatalog.find((g) => g.id === id);
      const slot = group ? group.slot_label : id;
      bySlot.set(slot, [...(bySlot.get(slot) || []), group ? group.label : id]);
    }
    const groups = [...bySlot].map(([slot, labels]) => `${slot}: ${labels.join(", ")}`).join("; ");
    const mode = backup.groups.some((id) => this.groupCatalog.find((g) => g.id === id)?.kind === "kwargs")
      ? ` (parameters: ${backup.kwargs_mode})`
      : "";
    return `from ${backup.source}: ${groups}${mode}`;
  },

  formatDate(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? String(iso || "") : date.toLocaleString();
  },

  pendingChanges(backup) {
    return backup.changes.filter((c) => !c.restored);
  },

  async loadBackups(silent = false) {
    if (!silent) this.history.loading = true;
    try {
      const response = await api("list_backups", {});
      this.history.items = response.backups || [];
      this.history.max = response.max_backups || 20;
    } catch (error) {
      toastError(message(error, "Could not load the history."));
    } finally {
      this.history.loading = false;
    }
  },

  undoHtml(backup) {
    const rows = this.pendingChanges(backup)
      .map((c) => `<li>${esc(c.preset)}${c.created ? " <em>(will be removed)</em>" : ""}</li>`)
      .join("");
    return `
      <p>Return these presets to how they were before <strong>${esc(this.formatDate(backup.created_at))}</strong>:</p>
      <ul>${rows}</ul>
      <p><strong>Their current settings will be overwritten.</strong></p>`;
  },

  conflictText(conflict) {
    return conflict === "missing" ? "no longer exists" : "edited afterwards";
  },

  async undo(backup) {
    if (this.history.busy || backup.undone) return;
    const confirmed = await showConfirmDialog({
      title: "Undo",
      message: this.undoHtml(backup),
      type: "warning",
      confirmText: "Restore",
      cancelText: "Cancel",
    });
    if (!confirmed) return;
    this.history.busy = true;
    try {
      let response = await api("undo_backup", { id: backup.id });
      if (response.has_conflicts) {
        const conflicted = response.results.filter((r) => r.conflict && !r.ok);
        const list = conflicted.map((r) => `<li>${esc(r.preset)}: ${esc(this.conflictText(r.conflict))}</li>`).join("");
        const force = await showConfirmDialog({
          title: "Changed since then",
          message: `<p>These presets were changed after the operation:</p><ul>${list}</ul>
            <p><strong>Restoring them will discard those later changes.</strong> Restore anyway?</p>`,
          type: "danger",
          confirmText: "Restore anyway",
          cancelText: "Keep them",
        });
        const restoredNow = response.results.filter((r) => r.ok).length;
        if (force) {
          const second = await api("undo_backup", { id: backup.id, force: true });
          response = { ...second, results: [...response.results.filter((r) => r.ok), ...second.results] };
        } else {
          if (restoredNow > 0) {
            toastSuccess(`Restored ${plural(restoredNow, "preset")}. The others were left as they are.`);
          }
          response = null;
        }
      }
      if (response) {
        const restored = response.results.filter((r) => r.ok).length;
        if (restored > 0) toastSuccess(`Restored ${plural(restored, "preset")}.`);
      }
    } catch (error) {
      toastError(message(error, "Could not restore the backup."));
    } finally {
      this.history.busy = false;
      await this.loadBackups(true);
      await this.load();
    }
  },

  async deleteBackup(backup) {
    if (this.history.busy) return;
    const confirmed = await showConfirmDialog({
      title: "Delete backup",
      message: "<p>You will no longer be able to undo this operation.</p>",
      type: "warning",
      confirmText: "Delete",
      cancelText: "Cancel",
    });
    if (!confirmed) return;
    await this.runDelete({ id: backup.id }, "Backup deleted.");
  },

  async deleteAllBackups() {
    if (this.history.busy || this.history.items.length === 0) return;
    const confirmed = await showConfirmDialog({
      title: "Delete all backups",
      message: `<p>Deletes all ${this.history.items.length} backups. You will no longer be able to undo those operations.</p>`,
      type: "danger",
      confirmText: "Delete all",
      cancelText: "Cancel",
    });
    if (!confirmed) return;
    await this.runDelete({ all: true }, "All backups deleted.");
  },

  async runDelete(payload, doneText) {
    this.history.busy = true;
    try {
      await api("delete_backup", payload);
      toastSuccess(doneText);
    } catch (error) {
      toastError(message(error, "Could not delete the backup."));
    } finally {
      this.history.busy = false;
      await this.loadBackups(true);
    }
  },
};

export const store = createStore("multiPresetManager", model);
