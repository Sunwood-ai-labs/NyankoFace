export type SpaceStatus =
  | 'queued'
  | 'leased'
  | 'building'
  | 'running'
  | 'stopping'
  | 'stopped'
  | 'unavailable'
  | 'failed'
  | 'error';

export type SpaceExecution = 'local-cpu' | 'remote-gpu';

export interface SpaceStatusInfo {
  status: SpaceStatus;
  execution: SpaceExecution;
}

export interface SpaceStatusRow extends SpaceStatusInfo {
  owner: string;
  repo: string;
}

const RUNNER_API = (process.env.RUNNER_API || 'http://spaces-runner:8000/api').replace(/\/$/, '');

export async function getSpaceStatuses(): Promise<Record<string, SpaceStatusInfo>> {
  try {
    const response = await fetch(`${RUNNER_API}/spaces`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`spaces HTTP ${response.status}`);
    const rows = await response.json() as SpaceStatusRow[];
    return Object.fromEntries(rows.map((row) => [
      `${row.owner}/${row.repo}`,
      { status: row.status, execution: row.execution || 'local-cpu' },
    ]));
  } catch {
    return {};
  }
}
