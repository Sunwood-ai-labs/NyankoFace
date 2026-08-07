'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import type { ForgejoBrowserSession } from '@/lib/forgejo-session-types';

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | ({
      status: 'authenticated';
    } & Required<Pick<ForgejoBrowserSession, 'username'>> &
      Omit<ForgejoBrowserSession, 'authenticated' | 'username'>);

interface AuthSessionContextValue {
  auth: AuthState;
  refreshAuth: () => Promise<void>;
  setAnonymous: () => void;
}

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);

function toAuthState(session: ForgejoBrowserSession): AuthState {
  return session.authenticated && session.username
    ? {
        status: 'authenticated',
        username: session.username,
        displayName: session.displayName,
        avatarUrl: session.avatarUrl,
        isAdmin: session.isAdmin,
      }
    : { status: 'anonymous' };
}

export default function AuthSessionProvider({
  initialSession,
  children,
}: {
  initialSession: ForgejoBrowserSession;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [auth, setAuth] = useState<AuthState>(() => toAuthState(initialSession));

  const refreshAuth = useCallback(async () => {
    try {
      const response = await fetch('/api/auth/session', {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`session HTTP ${response.status}`);
      setAuth(toAuthState((await response.json()) as ForgejoBrowserSession));
    } catch {
      setAuth({ status: 'anonymous' });
    }
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [pathname, refreshAuth]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void refreshAuth();
    };
    window.addEventListener('focus', refreshAuth);
    window.addEventListener('pageshow', refreshAuth);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      window.removeEventListener('focus', refreshAuth);
      window.removeEventListener('pageshow', refreshAuth);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, [refreshAuth]);

  const value = useMemo<AuthSessionContextValue>(
    () => ({
      auth,
      refreshAuth,
      setAnonymous: () => setAuth({ status: 'anonymous' }),
    }),
    [auth, refreshAuth],
  );

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession(): AuthSessionContextValue {
  const context = useContext(AuthSessionContext);
  if (!context) throw new Error('useAuthSession must be used inside AuthSessionProvider');
  return context;
}
