import { describe, it, expect, vi } from "vitest";
import {
  mergeJobs,
  intentKey,
  createTerminalAnnouncer,
  commandNotice,
} from "../src/state";
import { RETIRED_KINDS } from "../src/retired-kinds";
import type { Job } from "../src/types";
const job = (revision: number, state: string) =>
  ({ id: "a", revision, state }) as Job;
describe("retired review-copy and delivery jobs", () => {
  it.each(RETIRED_KINDS)("announces nothing for an old %s job", (kind) => {
    const speak = vi.fn();
    const announce = createTerminalAnnouncer(speak);
    const old = {
      ...job(1, "queued"),
      kind,
      title: "Old record",
      message: "",
    } as Job;
    announce([old]);
    announce([{ ...old, revision: 4, state: "succeeded" }]);
    expect(speak).not.toHaveBeenCalled();
  });
  it("still announces a finished inspection", () => {
    const speak = vi.fn();
    const announce = createTerminalAnnouncer(speak);
    const inspection = {
      ...job(1, "queued"),
      kind: "epub",
      title: "Book",
      message: "Done",
    } as Job;
    announce([inspection]);
    announce([{ ...inspection, revision: 2, state: "succeeded" }]);
    expect(speak).toHaveBeenCalledWith("Book: inspection completed. Done");
  });
});
describe("durable response ordering", () => {
  it("keeps confirmed cancellation when an old GET arrives", () => {
    expect(mergeJobs([job(5, "cancelled")], [job(3, "running")])[0].state).toBe(
      "cancelled",
    );
  });
  it("accepts progress and retains other known jobs", () => {
    const other = { ...job(1, "queued"), id: "b" };
    expect(
      mergeJobs([job(2, "running")], [job(3, "succeeded"), other]),
    ).toEqual([job(3, "succeeded"), other]);
  });
  it("reuses an ambiguous intent across reload and separates work keys", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        values.set(key, value);
      },
    };
    const first = intentKey(storage, "work-a");
    expect(intentKey(storage, "work-a")).toBe(first);
    expect(intentKey(storage, "work-b")).not.toBe(first);
  });
});

describe("terminal announcements", () => {
  it("announces a terminal transition once across repeated polling", () => {
    vi.useFakeTimers();
    try {
      const speak = vi.fn();
      const announce = createTerminalAnnouncer(speak);
      let jobs = [
        { ...job(1, "queued"), title: "Selected work", message: "Waiting" },
      ];
      announce(jobs);
      const poll = setInterval(() => announce(jobs), 1500);
      jobs = [
        {
          ...jobs[0],
          revision: 3,
          state: "failed",
          message: "Fixture source unavailable",
        },
      ];
      vi.advanceTimersByTime(6000);
      clearInterval(poll);
      expect(speak).toHaveBeenCalledTimes(1);
      expect(speak.mock.calls[0][0]).toContain("Selected work");
      expect(speak.mock.calls[0][0]).toContain("failed");
    } finally {
      vi.useRealTimers();
    }
  });
  it("keeps existing history quiet and includes every new terminal transition", () => {
    const speak = vi.fn();
    const announce = createTerminalAnnouncer(speak);
    announce([
      {
        ...job(4, "succeeded"),
        id: "past",
        title: "Past work",
        message: "Done",
      },
    ]);
    expect(speak).not.toHaveBeenCalled();
    const waiting = ["a", "b", "c"].map((id) => ({
      ...job(1, "running"),
      id,
      title: id,
      message: "Comparing",
    }));
    announce(waiting);
    announce(
      waiting.map((job, i) => ({
        ...job,
        revision: 4,
        state: ["succeeded", "failed", "cancelled"][i],
      })),
    );
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0]).toContain("completed");
    expect(speak.mock.calls[0][0]).toContain("failed");
    expect(speak.mock.calls[0][0]).toContain("cancelled");
  });
});

describe("command acknowledgement", () => {
  it("reports completion when cancel loses the completion race", () => {
    expect(commandNotice("cancel", job(6, "succeeded"))).toContain(
      "already completed",
    );
    expect(commandNotice("cancel", job(6, "succeeded"))).not.toContain(
      "cancelled",
    );
  });
  it("reports the actual terminal state for an idempotent replay", () => {
    expect(commandNotice("inspect", job(6, "succeeded"))).toContain(
      "completed",
    );
    expect(commandNotice("inspect", job(6, "failed"))).toContain("failed");
    expect(commandNotice("cancel", job(6, "cancelled"))).toContain("cancelled");
    expect(commandNotice("inspect", job(1, "queued"))).toContain("queued");
    expect(commandNotice("inspect", job(2, "running"))).toContain("running");
    expect(commandNotice("cancel", job(2, "running"))).toContain(
      "not confirmed",
    );
  });
});
