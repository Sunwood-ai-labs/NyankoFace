'use client';

import { createContext, useEffect, useState } from 'react';
import type { SpaceStatusInfo, SpaceStatusRow } from '@/lib/space-status';

export const SpaceStatusContext = createContext<Record<string, SpaceStatusInfo> | null>(null);

export default function SpaceStatusProvider({
  initialStatuses,
  children,
}: {
  initialStatuses: Record<string, SpaceStatusInfo>;
  children: React.ReactNode;
}) {
  const [statuses, setStatuses] = useState(initialStatuses);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch('/runner-api/spaces', { cache: 'no-store' });
        if (!response.ok) return;
        const rows = await response.json() as SpaceStatusRow[];
        if (active) {
          setStatuses(Object.fromEntries(rows.map((row) => [
            `${row.owner}/${row.repo}`,
            { status: row.status, execution: row.execution || 'local-cpu' },
          ])));
        }
      } catch {
        // Keep the last known status during a transient runner outage.
      }
    };
    const timer = window.setInterval(refresh, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return <SpaceStatusContext.Provider value={statuses}>{children}</SpaceStatusContext.Provider>;
}
