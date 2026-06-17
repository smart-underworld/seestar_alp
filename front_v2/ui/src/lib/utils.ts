/** Shared pure-function utilities used across v2 UI components. */

export function batteryColor(pct: number | null): "primary" | "danger" | "warning" | "success" {
  if (pct == null) return "primary";
  if (pct <= 10) return "danger";
  if (pct <= 20) return "warning";
  return "success";
}

export function storageFreeGB(raw: string): number {
  const m = raw?.match(/^([\d.]+)/);
  return m ? parseFloat(m[1]) : 0;
}

/** Returns free-storage as a % of total (for a metric bar). */
export function storagePct(raw: string): number {
  const m = raw?.match(/^([\d.]+)\s*GB\s*\/\s*([\d.]+)/);
  if (!m) return 0;
  return Math.min(100, Math.round((parseFloat(m[1]) / parseFloat(m[2])) * 100));
}

export function storageColor(raw: string): "danger" | "warning" | "success" {
  const gb = storageFreeGB(raw);
  if (gb <= 5) return "danger";
  if (gb <= 10) return "warning";
  return "success";
}

export type SettingGroup = "Imaging" | "Environment" | "Mount & Focus" | "General";

// Real device "stack" sub-object keys (no "stack_" prefix, so the regex
// below can't catch them) that are nonetheless imaging/stacking settings.
const IMAGING_KEYS = new Set([
  "dbe",
  "star_correction",
  "airplane_line_removal",
  "drizzle2x",
  "star_trails",
  "cont_capt",
  "wide_denoise",
]);

export function settingGroupFor(key: string): SettingGroup {
  if (IMAGING_KEYS.has(key)) return "Imaging";
  const k = key.toLowerCase();
  if (/gain|exp|stack|frame|light|lenhance|wide/.test(k)) return "Imaging";
  if (/temp|heater|dew/.test(k))                           return "Environment";
  if (/dither|focus|track|mount|calib/.test(k))            return "Mount & Focus";
  return "General";
}

/** Returns true if the nav href matches the current SPA location. */
export function isNavActive(href: string, location: string): boolean {
  if (href === "/") return location === "/" || location === "";
  return location.startsWith(href);
}
