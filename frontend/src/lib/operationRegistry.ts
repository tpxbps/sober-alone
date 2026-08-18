export class OperationRegistry {
  private readonly controllers = new Map<string, AbortController>()

  start(key: string): AbortController {
    this.controllers.get(key)?.abort()
    const controller = new AbortController()
    this.controllers.set(key, controller)
    return controller
  }

  isCurrent(key: string, controller: AbortController): boolean {
    return !controller.signal.aborted && this.controllers.get(key) === controller
  }

  finish(key: string, controller: AbortController): void {
    if (this.controllers.get(key) === controller) {
      this.controllers.delete(key)
    }
  }

  abortAll(): void {
    for (const controller of this.controllers.values()) controller.abort()
    this.controllers.clear()
  }
}
