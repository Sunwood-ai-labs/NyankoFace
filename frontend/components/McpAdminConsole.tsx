'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HfIcon from './HfIcon';
import { ui, type Locale } from '@/lib/i18n';
import {
  isActiveToken,
  isValidServiceAccountId,
  SERVICE_ACCOUNT_ID_PATTERN_SOURCE,
  tokenLifetimeSeconds,
} from '@/lib/mcp-admin-ui';

export async function preserveOneTimeResult<T>(
  result: T,
  reveal: (value: T) => void,
  refresh: () => Promise<unknown>,
): Promise<T> {
  reveal(result);
  try { await refresh(); } catch { /* One-time values must survive refresh failures. */ }
  return result;
}

type Account = { subject_id: string; enabled: boolean; forgejo_user_id: number; allowed_scopes: string[]; repository_permissions: Record<string, string>; mapping_version: number };
type Token = { token_id: string; subject_id: string; client_id: string; scopes: string[]; repositories: string[]; created_at: number; expires_at: number; revoked_at?: number | null };
type ToolPolicy = { scope: string; scope_id: string; tool: string; effect: string; version: number };
type ReadOnlyPolicy = { scope: string; scope_id: string; version: number };
type AuditItem = { sequence: number; occurred_at: number; event_type: string; outcome: string; subject_id: string; client_id: string; tool?: string | null; target?: string | null; reason_code: string; repository?: string | null; policy_version?: number | null; metadata?: unknown };
type AuditSummary = { total: number; by_outcome: Record<string, number>; by_tool: Record<string, number> };
type AdminState = { service_accounts: Account[]; tokens: Token[]; policy: { version: number; tools: ToolPolicy[]; read_only: ReadOnlyPolicy[] }; audit: { items: AuditItem[]; next_cursor?: number | null; summary: AuditSummary } };
type Secret = { token: string; token_id: string; client_id: string; expires_at: number };
type ConnectionReport = { reachable: boolean; ok: boolean; reason_code: string; tools: number | null; resources: number | null; checks: Record<string, { status?: number; ok: boolean; reason_code: string; count?: number }> };
type Tab = 'access' | 'policy' | 'audit' | 'clients';

const field = 'w-full rounded-xl border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-950 outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-200 dark:border-zinc-700 dark:bg-zinc-950 dark:text-white dark:focus:ring-violet-950';
const button = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-bold text-zinc-800 shadow-sm hover:border-violet-400 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100';
const primary = `${button} border-violet-600 bg-violet-600 text-white hover:bg-violet-700 hover:text-white dark:border-violet-500 dark:bg-violet-500 dark:text-zinc-950`;
const card = 'rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/80 sm:p-5';
const split = (value: FormDataEntryValue | null) => String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
const permissions = (value: FormDataEntryValue | null) => Object.fromEntries(split(value).map((item) => { const [repo, mode = 'read'] = item.split(':'); return [repo, mode]; }));
const formatTime = (value: number, locale: Locale) => new Intl.DateTimeFormat(locale === 'ja' ? 'ja-JP' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(value * 1000);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/admin/mcp/${path}`, { ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  const body = await response.json().catch(() => ({ error: 'invalid_response' }));
  if (!response.ok) throw new ApiError(String(body.error || `HTTP ${response.status}`), response.status);
  return body as T;
}

class ApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) { super(code); }
}

export default function McpAdminConsole({ locale }: { locale: Locale }) {
  const [tab, setTab] = useState<Tab>('access');
  const [state, setState] = useState<AdminState | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [auditQuery, setAuditQuery] = useState('limit=20');
  const [connection, setConnection] = useState<ConnectionReport | null>(null);
  const [needsReauth, setNeedsReauth] = useState(false);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const tokenActionLock = useRef(false);
  const releaseTokenAction = () => {
    tokenActionLock.current = false;
    setSecret(null);
    setConnection(null);
  };
  const tokenActionsDisabled = Boolean(busy) || secret !== null;
  const accountMutationsDisabled = Boolean(busy) || secret !== null;

  const load = useCallback(async (query = auditQuery) => {
    try { setState(await api<AdminState>(`state?${query}`)); setNeedsReauth(false); setNotice(''); }
    catch (error) {
      if (error instanceof ApiError && error.code === 'fresh_reauthentication_required') {
        setState(null); setNeedsReauth(true); setNotice('');
      } else setNotice(error instanceof Error ? error.message : 'request_failed');
    }
  }, [auditQuery]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const destroy = () => { releaseTokenAction(); };
    window.addEventListener('pagehide', destroy);
    window.addEventListener('beforeunload', destroy);
    return () => { destroy(); window.removeEventListener('pagehide', destroy); window.removeEventListener('beforeunload', destroy); };
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const mutate = async (name: string, path: string, method: string, payload?: unknown, refresh = true) => {
    setBusy(name); setNotice('');
    try { const result = await api<Record<string, unknown>>(path, { method, body: payload === undefined ? undefined : JSON.stringify(payload) }); if (refresh) await load(); return result; }
    catch (error) {
      if (error instanceof ApiError && error.code === 'fresh_reauthentication_required') {
        setState(null); setNeedsReauth(true); setNotice('');
      } else setNotice(error instanceof Error ? error.message : 'request_failed');
      return null;
    }
    finally { setBusy(''); }
  };

  const withTokenActionLock = async (
    action: () => Promise<Record<string, unknown> | null>,
  ): Promise<Record<string, unknown> | null> => {
    if (tokenActionLock.current) return null;
    tokenActionLock.current = true;
    try {
      const result = await action();
      if (!result?.token) tokenActionLock.current = false;
      return result;
    } catch (error) {
      tokenActionLock.current = false;
      throw error;
    }
  };

  const reauthenticate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    let password = String(data.get('password') || '');
    let otp = String(data.get('otp') || '').trim();
    setBusy('reauth'); setNotice('');
    try {
      const credentials: { password: string; otp?: string } = { password };
      if (otp) credentials.otp = otp;
      await api<{ ok: true }>('reauth', { method: 'POST', body: JSON.stringify(credentials) });
      setNeedsReauth(false);
      await load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'request_failed');
    } finally { password = ''; otp = ''; form.reset(); setBusy(''); }
  };

  const createAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    const subject = String(data.get('subject') || '').trim();
    if (!isValidServiceAccountId(subject)) {
      setNotice(ui(locale, 'Subject IDは英数字と : _ . - の1〜128文字で入力してください。', 'Subject ID must be 1-128 characters using letters, numbers, :, _, ., or -.'));
      return;
    }
    const result = await mutate('account', 'service-accounts', 'POST', { subject_id: subject, forgejo_user_id: Number(data.get('forgejoUser')), forgejo_token_ref: data.get('tokenRef'), allowed_scopes: split(data.get('scopes')), repository_permissions: permissions(data.get('repositories')) });
    if (result) form.reset();
  };
  const remapAccount = async (event: FormEvent<HTMLFormElement>, subject: string) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await mutate(`remap:${subject}`, `service-accounts/${encodeURIComponent(subject)}/remap`, 'POST', { forgejo_user_id: Number(data.get('forgejoUser')), forgejo_token_ref: data.get('tokenRef'), allowed_scopes: split(data.get('scopes')), repository_permissions: permissions(data.get('repositories')) });
  };
  const issue = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const result = await withTokenActionLock(() => mutate('issue', 'tokens', 'POST', { subject_id: data.get('subject'), client_id: data.get('client'), scopes: split(data.get('scopes')), repositories: split(data.get('repositories')), ttl_seconds: Number(data.get('ttl')) }, false));
    if (result?.token) await preserveOneTimeResult(result as unknown as Secret, (value) => { setSecret(value); setConnection(null); }, () => load());
  };
  const rotateToken = async (token: Token) => {
    const result = await withTokenActionLock(() => mutate(`rotate:${token.token_id}`, `tokens/${token.token_id}/rotate`, 'POST', { ttl_seconds: tokenLifetimeSeconds(token) }, false));
    if (result?.token) await preserveOneTimeResult(result as unknown as Secret, (value) => { setSecret(value); setConnection(null); }, () => load());
  };
  const revokeToken = async (token: Token) => {
    await withTokenActionLock(() => mutate(`revoke:${token.token_id}`, `tokens/${token.token_id}/revoke`, 'POST'));
  };
  const policy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!state) return; const data = new FormData(event.currentTarget);
    await mutate('policy', 'policies', 'PUT', { action: data.get('action'), scope: data.get('scope'), scope_id: data.get('scopeId'), tool: data.get('tool'), expected_version: state.policy.version });
  };
  const filterAudit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget); const query = new URLSearchParams({ limit: '20' });
    for (const key of ['outcome', 'tool', 'subject', 'client']) { const value = String(data.get(key) || '').trim(); if (value) query.set(key, value); }
    for (const key of ['after', 'before']) { const value = String(data.get(key) || '').trim(); if (value) query.set(key, String(Math.floor(new Date(value).getTime() / 1000))); }
    setAuditQuery(query.toString()); await load(query.toString());
  };

  const tabs: Array<[Tab, string]> = [['access', ui(locale, 'アカウントとToken', 'Accounts & tokens')], ['policy', ui(locale, 'ポリシー', 'Policy')], ['audit', ui(locale, '監査', 'Audit')], ['clients', ui(locale, '接続設定', 'Client setup')]];
  const activeTokens = useMemo(() => state?.tokens.filter((item) => isActiveToken(item, now)) || [], [now, state]);

  return <div className="grid gap-5">
    <nav aria-label={ui(locale, 'MCP管理セクション', 'MCP admin sections')} className="grid max-w-full grid-cols-2 gap-1 rounded-2xl border border-zinc-200 bg-zinc-50 p-1 dark:border-zinc-800 dark:bg-zinc-950 sm:flex">
      {tabs.map(([id, label]) => <button key={id} type="button" onClick={() => setTab(id)} aria-current={tab === id ? 'page' : undefined} className={`min-h-10 min-w-0 rounded-xl px-3 text-sm font-bold sm:shrink-0 sm:px-4 ${tab === id ? 'bg-white text-violet-700 shadow-sm dark:bg-zinc-800 dark:text-violet-200' : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'}`}>{label}</button>)}
    </nav>
    {notice && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{notice}</p>}
    {needsReauth && <section className={`${card} max-w-xl`}><h2 className="text-lg font-extrabold">{ui(locale, '管理操作を再認証', 'Reauthenticate administration')}</h2><p className="mt-2 text-sm leading-6 text-zinc-500">{ui(locale, 'Forgejoの現在のパスワードを確認します。2FAを有効にしている場合は認証アプリのコードも入力してください。値は保存されず、確認後に入力欄から破棄します。', 'Confirm your current Forgejo password. If Forgejo 2FA is enabled, enter the authenticator code too. Neither value is stored and both are cleared after verification.')}</p><form method="post" onSubmit={reauthenticate} className="mt-4 grid gap-3"><input required type="password" name="password" autoComplete="current-password" className={field} aria-label={ui(locale, 'Forgejoパスワード', 'Forgejo password')} /><input inputMode="numeric" maxLength={6} pattern="[0-9]{6}" name="otp" autoComplete="one-time-code" className={field} aria-label={ui(locale, 'Forgejo 2FAコード（任意）', 'Forgejo 2FA code (optional)')} placeholder={ui(locale, '2FAコード（任意）', '2FA code (optional)')} /><button className={primary} disabled={busy === 'reauth'}><HfIcon name="key" className="h-4 w-4" />{ui(locale, '確認して続行', 'Verify and continue')}</button></form></section>}
    {!state && !notice && !needsReauth && <p className="flex items-center gap-2 text-sm text-zinc-500"><HfIcon name="spinner" className="h-4 w-4 animate-spin" />{ui(locale, '読み込み中…', 'Loading…')}</p>}

    {state && tab === 'access' && <div className="grid gap-5 xl:grid-cols-2">
      <section className={card}>
        <h2 className="text-lg font-extrabold text-zinc-950 dark:text-white">{ui(locale, 'サービスアカウント', 'Service accounts')}</h2>
        <div className="mt-4 grid gap-3">{state.service_accounts.map((account) => <article key={account.subject_id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-700">
          <div className="flex flex-wrap items-center justify-between gap-2"><strong className="break-all text-sm">{account.subject_id}</strong><span className={`rounded-full px-2 py-1 text-xs font-bold ${account.enabled ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'}`}>{account.enabled ? ui(locale, '有効', 'Active') : ui(locale, '無効', 'Disabled')}</span></div>
          <p className="mt-2 break-words text-xs leading-5 text-zinc-500">Forgejo #{account.forgejo_user_id} · v{account.mapping_version}<br />{account.allowed_scopes.join(', ')}</p>
           <div className="mt-3 flex flex-wrap gap-2">{account.enabled && <button type="button" className={button} disabled={accountMutationsDisabled} onClick={() => void mutate(account.subject_id, `service-accounts/${encodeURIComponent(account.subject_id)}/disable`, 'POST')}>{ui(locale, '無効化', 'Disable')}</button>}<details className="w-full"><summary className="cursor-pointer text-xs font-bold text-violet-700 dark:text-violet-300">{ui(locale, '対応付けを変更', 'Change mapping')}</summary><form onSubmit={(event) => void remapAccount(event, account.subject_id)} className="mt-3 grid gap-2"><input required min="1" type="number" name="forgejoUser" className={field} defaultValue={account.forgejo_user_id} aria-label="New Forgejo user ID" /><input required name="tokenRef" className={field} placeholder="secret reference" aria-label="New Forgejo token secret reference" /><input required name="scopes" className={field} defaultValue={account.allowed_scopes.join(', ')} aria-label="New allowed scopes" /><input required name="repositories" className={field} defaultValue={Object.entries(account.repository_permissions).map(([repo, mode]) => `${repo}:${mode}`).join(', ')} aria-label="New repository permissions" /><button className={button} disabled={accountMutationsDisabled}>{ui(locale, '再マッピング', 'Remap')}</button></form></details></div>
        </article>)}</div>
        <form onSubmit={createAccount} className="mt-5 grid gap-3 border-t border-zinc-200 pt-5 dark:border-zinc-700">
          <h3 className="font-bold">{ui(locale, 'アカウントを追加', 'Add account')}</h3>
          <input required name="subject" maxLength={128} pattern={SERVICE_ACCOUNT_ID_PATTERN_SOURCE} className={field} placeholder="service:docs-agent" aria-label="Subject ID" />
          <div className="grid gap-3 sm:grid-cols-2"><input required min="1" type="number" name="forgejoUser" className={field} placeholder="Forgejo user ID" aria-label="Forgejo user ID" /><input required name="tokenRef" className={field} placeholder="secret reference" aria-label="Forgejo token secret reference" /></div>
          <input required name="scopes" className={field} placeholder="catalog:read, repos:read" aria-label="Allowed scopes" />
          <input required name="repositories" className={field} placeholder="owner/repo:read, owner/docs:write" aria-label="Repository permissions" />
           <button className={primary} disabled={accountMutationsDisabled}>{ui(locale, '追加', 'Add account')}</button>
        </form>
      </section>
      <section className={card}>
        <h2 className="text-lg font-extrabold text-zinc-950 dark:text-white">Token</h2>
        <form onSubmit={issue} className="mt-4 grid gap-3">
          <select required name="subject" className={field} aria-label="Service account"><option value="">{ui(locale, 'アカウントを選択', 'Select an account')}</option>{state.service_accounts.filter((item) => item.enabled).map((item) => <option key={item.subject_id}>{item.subject_id}</option>)}</select>
          <input required name="client" className={field} placeholder="codex-cli" aria-label="Client ID" />
          <input required name="scopes" className={field} placeholder="catalog:read, repos:read" aria-label="Token scopes" />
          <input required name="repositories" className={field} placeholder="owner/repo" aria-label="Token repositories" />
          <label className="text-xs font-bold text-zinc-600 dark:text-zinc-300">TTL (seconds)<input required min="60" max="7776000" type="number" name="ttl" defaultValue="2592000" className={`${field} mt-1`} /></label>
          <button className={primary} disabled={tokenActionsDisabled}><HfIcon name="key" className="h-4 w-4" />{ui(locale, '最小権限Tokenを発行', 'Issue least-privilege token')}</button>
        </form>
        <div className="mt-5 grid gap-3 border-t border-zinc-200 pt-5 dark:border-zinc-700">{activeTokens.map((token) => <article key={token.token_id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-700">
          <strong className="break-all text-sm">{token.client_id}</strong><p className="mt-1 break-all text-xs text-zinc-500">{token.token_id}<br />{token.scopes.join(', ')}<br />{ui(locale, '期限', 'Expires')}: {formatTime(token.expires_at, locale)}</p>
          <div className="mt-3 flex flex-wrap gap-2"><button type="button" className={button} disabled={tokenActionsDisabled} onClick={() => void rotateToken(token)}>{ui(locale, 'ローテーション', 'Rotate')}</button><button type="button" className={button} disabled={tokenActionsDisabled} onClick={() => void revokeToken(token)}>{ui(locale, '失効', 'Revoke')}</button></div>
        </article>)}</div>
      </section>
    </div>}

    {state && tab === 'policy' && <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_1fr]">
      <section className={card}><div className="flex items-center justify-between gap-3"><h2 className="text-lg font-extrabold">Policy</h2><span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-800 dark:bg-violet-950 dark:text-violet-200">revision {state.policy.version}</span></div>
        <p className="mt-2 text-sm leading-6 text-zinc-500">{ui(locale, '保存時にrevisionを照合し、競合を拒否します。変更は次のMCPリクエストから適用されます。', 'The current revision is checked on save. Changes apply to the next MCP request.')}</p>
        <form onSubmit={policy} className="mt-4 grid gap-3"><select name="action" className={field}><option value="allow">allow</option><option value="deny">deny</option><option value="delete">delete</option><option value="read-only">read-only</option><option value="read-write">read-write</option></select><select name="scope" className={field}><option value="global">global</option><option value="repository">repository</option><option value="service_account">service_account</option><option value="subject">subject</option></select><input required name="scopeId" className={field} defaultValue="*" aria-label="Scope ID" /><input name="tool" className={field} placeholder="search_catalog" aria-label="Tool name" /><button className={primary} disabled={Boolean(busy)}>{ui(locale, 'Policyを保存', 'Save policy')}</button></form>
      </section>
      <section className={card}><h2 className="text-lg font-extrabold">{ui(locale, '有効なルール', 'Active rules')}</h2><div className="mt-4 grid gap-2">{state.policy.tools.map((rule) => <p key={`${rule.scope}:${rule.scope_id}:${rule.tool}`} className="break-words rounded-xl bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-950"><strong>{rule.effect}</strong> · {rule.scope}:{rule.scope_id} · {rule.tool}</p>)}{state.policy.read_only.map((rule) => <p key={`${rule.scope}:${rule.scope_id}:ro`} className="rounded-xl bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-950"><strong>read-only</strong> · {rule.scope}:{rule.scope_id}</p>)}{!state.policy.tools.length && !state.policy.read_only.length && <p className="text-sm text-zinc-500">{ui(locale, '明示ルールはありません（既定は拒否）。', 'No explicit rules. Default is deny.')}</p>}</div></section>
    </div>}

    {state && tab === 'audit' && <section className={card}><h2 className="text-lg font-extrabold">{ui(locale, '監査証跡', 'Audit trail')}</h2><div className="mt-4 flex flex-wrap gap-2" aria-label={ui(locale, '利用状況の集計', 'Usage summary')}><span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-bold dark:bg-zinc-800">{ui(locale, '合計', 'Total')} {state.audit.summary.total}</span>{Object.entries(state.audit.summary.by_outcome).map(([outcome, count]) => <span key={outcome} className="rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-800 dark:bg-violet-950 dark:text-violet-200">{outcome} {count}</span>)}</div><form onSubmit={filterAudit} className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><input name="subject" className={field} placeholder="subject" /><input name="client" className={field} placeholder="client" /><input name="tool" className={field} placeholder="tool" /><select name="outcome" className={field}><option value="">all results</option><option>allowed</option><option>denied</option><option>failed</option><option>replayed</option><option>changed</option></select><label className="text-xs font-bold text-zinc-600 dark:text-zinc-300">{ui(locale, '開始', 'From')}<input type="datetime-local" name="after" className={`${field} mt-1`} /></label><label className="text-xs font-bold text-zinc-600 dark:text-zinc-300">{ui(locale, '終了', 'To')}<input type="datetime-local" name="before" className={`${field} mt-1`} /></label><button className={button}><HfIcon name="filter" className="h-4 w-4" />{ui(locale, '絞り込む', 'Filter')}</button></form>
      <div className="mt-5 grid gap-3">{state.audit.items.map((item) => <details key={item.sequence} className="group rounded-xl border border-zinc-200 p-3 dark:border-zinc-700"><summary className="cursor-pointer list-none"><div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><span className="min-w-0 break-words text-sm font-bold">{item.event_type} · {item.subject_id}</span><span className="text-xs text-zinc-500">{formatTime(item.occurred_at, locale)}</span></div><p className="mt-1 break-words text-xs text-zinc-500">{item.outcome} · {item.reason_code}{item.tool ? ` · ${item.tool}` : ''}</p></summary><dl className="mt-3 grid gap-2 border-t border-zinc-200 pt-3 text-xs dark:border-zinc-700"><div><dt className="font-bold">Target</dt><dd className="break-all">{item.target || '—'}</dd></div><div><dt className="font-bold">Repository</dt><dd>{item.repository || '—'}</dd></div><div><dt className="font-bold">Policy revision</dt><dd>{item.policy_version ?? '—'}</dd></div><div><dt className="font-bold">Metadata</dt><dd className="break-all font-mono">{JSON.stringify(item.metadata || {})}</dd></div></dl></details>)}{!state.audit.items.length && <p className="text-sm text-zinc-500">{ui(locale, '一致する記録はありません。', 'No matching records.')}</p>}</div>
      {state.audit.next_cursor && <button type="button" className={`${button} mt-4`} onClick={() => { const params = new URLSearchParams(auditQuery); params.set('cursor', String(state.audit.next_cursor)); const query = params.toString(); setAuditQuery(query); void load(query); }}>{ui(locale, '次のページ', 'Next page')}</button>}
    </section>}

    {tab === 'clients' && <section className={card}><h2 className="text-lg font-extrabold">{ui(locale, 'クライアント設定', 'Client setup')}</h2><p className="mt-2 text-sm text-zinc-500">{ui(locale, 'Token本体は貼り付けず、制限されたTokenファイルまたは秘密入力を参照してください。', 'Never embed token plaintext. Refer to a restricted token file or secret input.')}</p><div className="mt-5 grid gap-4 lg:grid-cols-3">
      <Snippet title="Codex" code={'$env:NYANKOFACE_MCP_TOKEN = (Get-Content $env:NYANKOFACE_MCP_TOKEN_FILE -Raw).Trim()\ncodex mcp add nyankoface --url https://<NYANKOFACE_HOST>/mcp --bearer-token-env-var NYANKOFACE_MCP_TOKEN'} />
      <Snippet title="Claude Desktop" code={'{\n  "mcpServers": {\n    "nyankoface": {\n      "command": "nyankoface-mcp-stdio",\n      "env": {\n        "NYANKOFACE_MCP_REMOTE_URL": "https://<NYANKOFACE_HOST>/mcp",\n        "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "<TOKEN_FILE>"\n      }\n    }\n  }\n}'} />
      <Snippet title="VS Code" code={'{\n  "servers": {\n    "nyankoface": {\n      "type": "http",\n      "url": "https://<NYANKOFACE_HOST>/mcp",\n      "headers": { "Authorization": "Bearer ${input:nyankoface-token}" }\n    }\n  },\n  "inputs": [\n    {\n      "id": "nyankoface-token",\n      "type": "promptString",\n      "description": "NyankoFace MCP token",\n      "password": true\n    }\n  ]\n}'} />
    </div></section>}

    {secret && <div role="dialog" aria-modal="true" aria-labelledby="mcp-secret-title" className="fixed inset-0 z-50 grid place-items-center bg-zinc-950/70 p-4" onKeyDown={(event) => { if (event.key === 'Escape') releaseTokenAction(); }}>
      <div className="w-full max-w-xl rounded-2xl bg-white p-5 shadow-2xl dark:bg-zinc-900 sm:p-6"><h2 id="mcp-secret-title" className="text-xl font-extrabold">{ui(locale, 'Tokenを今すぐ保存', 'Save this token now')}</h2><p className="mt-2 text-sm leading-6 text-amber-700 dark:text-amber-300">{ui(locale, 'この値は再表示できません。コピーまたは閉じると、この画面のメモリから破棄します。', 'This value cannot be shown again. Copying or closing destroys it from this screen.')}</p><pre className="mt-4 max-w-full overflow-x-auto rounded-xl bg-zinc-950 p-4 text-xs text-emerald-300"><code>{secret.token}</code></pre>
        {connection && <ConnectionStatus report={connection} locale={locale} />}
        <div className="mt-5 flex flex-wrap gap-2"><button type="button" className={primary} onClick={async () => { await navigator.clipboard.writeText(secret.token); releaseTokenAction(); setNotice(ui(locale, 'Tokenをコピーし、画面から破棄しました。', 'Token copied and destroyed from the screen.')); }}><HfIcon name="copy" className="h-4 w-4" />{ui(locale, 'コピーして閉じる', 'Copy and close')}</button><button type="button" className={button} onClick={async () => { setBusy('connection'); try { setConnection(await api<ConnectionReport>('connection-tests', { method: 'POST', body: JSON.stringify({ token: secret.token }) })); } catch { setConnection({ reachable: false, ok: false, reason_code: 'connection_test_failed', tools: null, resources: null, checks: {} }); } finally { setBusy(''); } }} disabled={busy === 'connection'}>{ui(locale, '接続を確認', 'Test connection')}</button><button type="button" className={button} onClick={() => releaseTokenAction()}>{ui(locale, '破棄して閉じる', 'Destroy and close')}</button></div>
      </div>
    </div>}
  </div>;
}

function Snippet({ title, code }: { title: string; code: string }) {
  return <article className="min-w-0 rounded-xl border border-zinc-200 p-3 dark:border-zinc-700"><h3 className="font-bold">{title}</h3><pre className="mt-3 max-w-full overflow-x-auto rounded-lg bg-zinc-950 p-3 text-xs leading-5 text-zinc-100"><code>{code}</code></pre></article>;
}

function ConnectionStatus({ report, locale }: { report: ConnectionReport; locale: Locale }) {
  return <section role="status" className={`mt-3 rounded-xl border p-3 text-sm ${report.ok ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100' : 'border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-100'}`}>
    <strong>{report.ok ? ui(locale, '接続成功', 'Connection ready') : ui(locale, '接続を確認できません', 'Connection not ready')}</strong>
    <p className="mt-1 text-xs">{report.reason_code} · {ui(locale, '到達性', 'Reachable')}: {report.reachable ? 'yes' : 'no'} · Tools: {report.tools ?? '—'} · Resources: {report.resources ?? '—'}</p>
    <ul className="mt-2 grid gap-1 text-xs">{Object.entries(report.checks).map(([name, check]) => <li key={name}><strong>{name}</strong>: {check.reason_code}{check.status ? ` · HTTP ${check.status}` : ''}{check.count !== undefined ? ` · ${check.count}` : ''}</li>)}</ul>
  </section>;
}
