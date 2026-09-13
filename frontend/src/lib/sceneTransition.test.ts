import { afterEach, expect, it, vi } from "vitest";
import { transitionScene } from "./sceneTransition";

afterEach(() => vi.unstubAllGlobals());

it("switches immediately in static mode and browsers without view transitions", async () => {
  vi.stubGlobal("document", {});
  const update = vi.fn();
  await transitionScene(update);
  expect(update).toHaveBeenCalledOnce();
  const startViewTransition = vi.fn();
  vi.stubGlobal("document", { startViewTransition });
  await transitionScene(update, true);
  expect(startViewTransition).not.toHaveBeenCalled();
  expect(update).toHaveBeenCalledTimes(2);
});

it("a skipped snapshot cannot later apply a stale navigation callback", async () => {
  const callbacks: Array<() => void> = [];
  const skip = vi.fn();
  vi.stubGlobal("document", {
    startViewTransition: (update: () => void) => {
      callbacks.push(update);
      return { skipTransition: skip, finished: Promise.resolve() };
    },
  });
  const stale = vi.fn(), latest = vi.fn();
  const first = transitionScene(stale);
  const second = transitionScene(latest);
  callbacks[0](); callbacks[1]();
  await Promise.all([first, second]);
  expect(skip).toHaveBeenCalledOnce();
  expect(stale).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledOnce();
});
