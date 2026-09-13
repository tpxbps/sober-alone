import { describe, expect, it } from "vitest";
import { FrameBudget } from "./frameBudget";

describe("optional animation frame budget", () => {
  it("keeps ordinary 30/60fps animation and isolated long tasks", () => {
    const budget = new FrameBudget();
    let now = 1;
    for (let i = 0; i < 180; i++) {
      now += i === 70 ? 2000 : i % 2 ? 16 : 33;
      expect(budget.exceeded(now)).toBe(false);
    }
  });
  it("detects sustained software-renderer slowness after warmup", () => {
    const budget = new FrameBudget();
    const observations = Array.from({ length: 30 }, (_, i) => budget.exceeded(1 + i * 150));
    expect(observations.slice(0, 20)).not.toContain(true);
    expect(observations).toContain(true);
  });
  it("does not count time in a hidden page or paused modal", () => {
    const budget = new FrameBudget();
    for (let i = 0; i < 15; i++) budget.exceeded(1 + i * 150);
    budget.reset();
    for (let i = 0; i < 100; i++) expect(budget.exceeded(60000 + i * 16)).toBe(false);
  });
});
