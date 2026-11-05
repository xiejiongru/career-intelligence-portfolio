// The private layer: application status and notes, keyed by job_id, stored only in this
// browser. It is never part of the published snapshot and never leaves the machine except
// through a file the user exports themselves.

const OVERLAY_KEY = "jobdash.overlay.v1";

export const STATUSES = ["未处理", "已投递", "已回复", "面试中", "Offer", "拒绝", "放弃", "已关闭"];

export function createOverlay() {
  let data = read();
  const listeners = new Set();

  function read() {
    try {
      return JSON.parse(localStorage.getItem(OVERLAY_KEY) || "{}");
    } catch {
      return {};
    }
  }

  function persist() {
    try {
      localStorage.setItem(OVERLAY_KEY, JSON.stringify(data));
      listeners.forEach((fn) => fn());
      return true;
    } catch (error) {
      // A full localStorage is the realistic failure here, not a corrupted one.
      window.dispatchEvent(
        new CustomEvent("jobdash:error", { detail: `本地存储写入失败：${error.name}。导出备注后清理旧条目。` })
      );
      return false;
    }
  }

  return {
    get(jobId) {
      return data[jobId] || {};
    },
    set(jobId, patch) {
      const next = { ...data[jobId], ...patch, updated_at: new Date().toISOString() };
      if (!next.status && !next.notes && !next.contact) delete data[jobId];
      else data[jobId] = next;
      persist();
    },
    all() {
      return data;
    },
    count() {
      return Object.keys(data).length;
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    exportText() {
      return JSON.stringify({ kind: "jobdash.overlay", version: 1, exported_at: new Date().toISOString(), entries: data }, null, 2);
    },
    importText(text, mode = "merge") {
      const parsed = JSON.parse(text);
      const entries = parsed.entries || parsed;
      if (mode === "replace") data = {};
      for (const [jobId, value] of Object.entries(entries)) {
        if (value && typeof value === "object") data[jobId] = { ...data[jobId], ...value };
      }
      persist();
      return Object.keys(entries).length;
    },
    clear() {
      data = {};
      persist();
    },
  };
}
