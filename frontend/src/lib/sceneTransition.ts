let active: ViewTransition | undefined;
let revision = 0;

/** Keep the outgoing composition visible while the next scene resolves into it. */
export function transitionScene(update: () => void, quiet = false): Promise<void> {
  const ticket = ++revision;
  active?.skipTransition();
  active = undefined;
  if (quiet || !document.startViewTransition || document.hidden) {
    update();
    return Promise.resolve();
  }
  const transition = document.startViewTransition(() => {
    if (ticket === revision) update();
  });
  active = transition;
  return transition.finished.catch(() => {}).finally(() => {
    if (active === transition) active = undefined;
  });
}
