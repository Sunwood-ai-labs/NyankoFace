export type ServerPhase = 'api' | 'db' | 'forgejo' | 'markdown' | 'permission' | 'runtime' | 'iframe';

export class ServerTimingTrace {
  private readonly phases = new Map<ServerPhase, number>();

  async measure<T>(phase: ServerPhase, task: () => Promise<T>): Promise<T> {
    const startedAt = performance.now();
    try {
      return await task();
    } finally {
      this.add(phase, performance.now() - startedAt);
    }
  }

  measureSync<T>(phase: ServerPhase, task: () => T): T {
    const startedAt = performance.now();
    try {
      return task();
    } finally {
      this.add(phase, performance.now() - startedAt);
    }
  }

  add(phase: ServerPhase, durationMs: number) {
    const current = this.phases.get(phase) ?? 0;
    this.phases.set(phase, current + Math.max(0, durationMs));
  }

  serialize(): string {
    return [...this.phases.entries()]
      .map(([phase, duration]) => `${phase};dur=${duration.toFixed(1)}`)
      .join(', ');
  }

  log(route: string) {
    if (process.env.NYANKOFACE_PERFORMANCE_LOG !== '1') return;
    console.info(JSON.stringify({
      event: 'nyankoface.server-timing',
      route,
      phases: Object.fromEntries([...this.phases.entries()].map(([phase, duration]) => [phase, Math.round(duration * 10) / 10])),
    }));
  }
}
