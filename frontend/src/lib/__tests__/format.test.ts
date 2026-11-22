import { describe, expect, it } from "vitest";
import { dueLabel, friendlyDate, parseServerDate } from "../format";

describe("server dates", () => {
  it("reads offset-less backend timestamps as UTC", () => {
    expect(parseServerDate("2026-09-10T08:00:00")?.toISOString()).toBe("2026-09-10T08:00:00.000Z");
    expect(parseServerDate("2026-09-10T08:00:00Z")?.toISOString()).toBe("2026-09-10T08:00:00.000Z");
    expect(parseServerDate("2026-09-10T16:00:00+08:00")?.toISOString()).toBe("2026-09-10T08:00:00.000Z");
    expect(parseServerDate("")).toBeNull();
    expect(parseServerDate("not a date")).toBeNull();
  });

  it("marks an item due only once its UTC time has passed", () => {
    const now = new Date("2026-09-10T08:30:00Z");
    expect(dueLabel("2026-09-10T08:00:00", now).due).toBe(true);
    expect(dueLabel("2026-09-10T09:00:00", now).due).toBe(false);
    expect(dueLabel(null, now).due).toBe(true);
  });

  it("uses relative words for recent days", () => {
    const now = new Date(2026, 8, 10, 12);
    expect(friendlyDate(new Date(2026, 8, 10, 9).toISOString(), now)).toBe("今天");
    expect(friendlyDate(new Date(2026, 8, 9, 9).toISOString(), now)).toBe("昨天");
  });
});
