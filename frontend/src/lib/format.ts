import api from "./api";

/**
 * The backend stores naive UTC datetimes and serialises them without an offset.
 * `new Date("2026-01-01T08:00:00")` would read that as local time, shifting due
 * dates by the viewer's timezone. Treat offset-less timestamps as UTC.
 */
export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const date = new Date(hasZone || !value.includes("T") ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

const relative = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });

/** "今天" / "昨天" / "3 天前" / "2026/9/1" — compact, human dates for lists. */
export function friendlyDate(value: string | null | undefined, now = new Date()): string {
  const date = parseServerDate(value);
  if (!date) return "";
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(date) - startOfDay(now)) / 86_400_000);
  if (Math.abs(days) <= 6) return relative.format(days, "day");
  return date.toLocaleDateString("zh-CN", {
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Due-ness of a spaced-repetition item. */
export function dueLabel(value: string | null | undefined, now = new Date()): { due: boolean; label: string } {
  const date = parseServerDate(value);
  if (!date || date.getTime() <= now.getTime()) return { due: true, label: "待复习" };
  return { due: false, label: `下次 ${friendlyDate(value, now)}` };
}

/** Download an authenticated API resource as a file. */
export async function downloadFile(path: string, filename: string, type?: string) {
  const { data } = await api.get(path, { responseType: "blob" });
  const blob = type ? new Blob([data], { type }) : (data as Blob);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
