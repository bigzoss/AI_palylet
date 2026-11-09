import { describe, expect, it } from "vitest";
import { pollInterval, timecode, type Job } from "./types";
describe("task lifecycle and media timing", () => {
  it("stops polling on terminal states", () => {
    expect(pollInterval([{ status: "running" } as Job])).toBe(2000);
    for (const status of ["succeeded", "failed", "cancelled"])
      expect(pollInterval([{ status } as Job])).toBe(false);
  });
  it("keeps precise fractional timecodes", () => {
    expect(timecode(65300)).toBe("01:05.3");
    expect(timecode()).toBe("00:00.0");
  });
});
