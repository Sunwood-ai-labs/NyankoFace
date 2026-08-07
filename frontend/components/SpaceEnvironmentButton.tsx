'use client';

import { FormEvent, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

type EnvironmentItem = {
  name: string;
  kind: 'variable' | 'secret';
  scope: 'runtime' | 'build' | 'both';
  configured: boolean;
  enabled: boolean;
  value?: string;
  updated_at?: string;
};

export default function SpaceEnvironmentButton({ owner, repo }: { owner: string; repo: string }) {
  const { locale } = useLocale();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<EnvironmentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [kind, setKind] = useState<'variable' | 'secret'>('secret');
  const [scope, setScope] = useState<'runtime' | 'build' | 'both'>('runtime');
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const base = `/api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/environment`;

  async function load() {
    setLoading(true);
    try {
      const response = await fetch(base, { cache: 'no-store' });
      const body = await response.json().catch(() => ({})) as { items?: EnvironmentItem[]; error?: string };
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
      setItems(body.items || []);
    } catch (error) {
      setNotice({
        kind: 'error',
        text: error instanceof Error ? error.message : ui(locale, '設定を取得できませんでした。', 'Could not load settings.'),
      });
    } finally {
      setLoading(false);
    }
  }

  async function show() {
    setOpen(true);
    setNotice(null);
    await load();
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const response = await fetch(base, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, kind, value, scope }),
      });
      const body = await response.json().catch(() => ({})) as EnvironmentItem & { error?: string; detail?: string };
      if (!response.ok) throw new Error(body.error || body.detail || `HTTP ${response.status}`);
      setName('');
      setValue('');
      setNotice({
        kind: 'success',
        text: kind === 'secret'
          ? ui(locale, 'Secretを保存しました。値は再表示されません。', 'Secret saved. Its value will not be shown again.')
          : ui(locale, 'Variableを保存しました。', 'Variable saved.'),
      });
      await load();
    } catch (error) {
      setNotice({
        kind: 'error',
        text: error instanceof Error ? error.message : ui(locale, '保存できませんでした。', 'Could not save the setting.'),
      });
    } finally {
      setSaving(false);
    }
  }

  async function remove(itemName: string) {
    if (pendingDelete !== itemName) {
      setPendingDelete(itemName);
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const response = await fetch(`${base}/${encodeURIComponent(itemName)}`, {
        method: 'DELETE',
      });
      const body = await response.json().catch(() => ({})) as { error?: string; detail?: string };
      if (!response.ok) throw new Error(body.error || body.detail || `HTTP ${response.status}`);
      setPendingDelete(null);
      setNotice({ kind: 'success', text: ui(locale, `${itemName}を削除しました。`, `${itemName} deleted.`) });
      await load();
    } catch (error) {
      setNotice({
        kind: 'error',
        text: error instanceof Error ? error.message : ui(locale, '削除できませんでした。', 'Could not delete the setting.'),
      });
    } finally {
      setSaving(false);
    }
  }

  async function setEnabled(item: EnvironmentItem) {
    setSaving(true);
    setNotice(null);
    try {
      const response = await fetch(`${base}/${encodeURIComponent(item.name)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !item.enabled }),
      });
      const body = await response.json().catch(() => ({})) as { error?: string; detail?: string };
      if (!response.ok) throw new Error(body.error || body.detail || `HTTP ${response.status}`);
      setNotice({
        kind: 'success',
        text: !item.enabled
          ? ui(locale, `${item.name}を有効にしました。`, `${item.name} enabled.`)
          : ui(locale, `${item.name}を無効にしました。`, `${item.name} disabled.`),
      });
      await load();
    } catch (error) {
      setNotice({
        kind: 'error',
        text: error instanceof Error ? error.message : ui(locale, '状態を変更できませんでした。', 'Could not change the setting state.'),
      });
    } finally {
      setSaving(false);
    }
  }

  function edit(item: EnvironmentItem) {
    setKind(item.kind);
    setScope(item.scope);
    setName(item.name);
    setValue(item.kind === 'variable' ? item.value || '' : '');
    setNotice(null);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void show()}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
        aria-label={ui(locale, 'VariablesとSecretsを管理', 'Manage Variables and Secrets')}
      >
        <HfIcon name="key" className="h-3 w-3" />
        <span className="max-sm:hidden">{ui(locale, 'VariablesとSecrets', 'Variables & Secrets')}</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[100] grid place-items-center bg-zinc-950/60 p-4 backdrop-blur-sm">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="space-environment-title"
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-950"
          >
            <header className="flex items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <div>
                <h2 id="space-environment-title" className="text-lg font-bold text-zinc-950 dark:text-white">
                  {ui(locale, 'VariablesとSecrets', 'Variables & Secrets')}
                </h2>
                <p className="mt-1 text-sm text-zinc-500">
                  {owner}/{repo} · runtime / build
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-lg border border-zinc-200 text-lg hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                aria-label={ui(locale, '閉じる', 'Close')}
              >
                ×
              </button>
            </header>

            <div className="space-y-5 p-5">
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                {ui(
                  locale,
                  'Secretは暗号化して保存され、保存後は値を再表示しません。build対象はForgejo Actionsへ同期され、fork由来のPull RequestにはForgejoの保護規則により渡されません。',
                  'Secrets are encrypted and never shown after saving. Build-scoped values sync to Forgejo Actions and are withheld from fork pull requests by Forgejo protections.',
                )}
              </div>

              <form
                onSubmit={save}
                autoComplete="off"
                data-navigation-feedback="off"
                className="grid gap-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800"
              >
                <div className="grid gap-3 sm:grid-cols-[130px_150px_1fr]">
                  <label className="grid gap-1 text-sm font-semibold">
                    {ui(locale, '種類', 'Type')}
                    <select
                      value={kind}
                      onChange={(event) => setKind(event.target.value as 'variable' | 'secret')}
                      className="h-10 rounded-lg border border-zinc-300 bg-white px-3 dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      <option value="secret">Secret</option>
                      <option value="variable">Variable</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm font-semibold">
                    {ui(locale, '適用先', 'Scope')}
                    <select
                      value={scope}
                      onChange={(event) => setScope(event.target.value as 'runtime' | 'build' | 'both')}
                      className="h-10 rounded-lg border border-zinc-300 bg-white px-3 dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      <option value="runtime">runtime</option>
                      <option value="build">build</option>
                      <option value="both">both</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm font-semibold">
                    {ui(locale, '環境変数名', 'Environment name')}
                    <input
                      required
                      pattern="[A-Z_][A-Z0-9_]{0,126}"
                      autoComplete="off"
                      data-form-type="other"
                      value={name}
                      onChange={(event) => setName(event.target.value.toUpperCase())}
                      placeholder="OPENAI_API_KEY"
                      className="h-10 rounded-lg border border-zinc-300 px-3 font-mono uppercase dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                </div>
                <label className="grid gap-1 text-sm font-semibold">
                  {kind === 'secret' ? ui(locale, 'Secret値', 'Secret value') : ui(locale, 'Variable値', 'Variable value')}
                  <input
                    required
                    type={kind === 'secret' ? 'password' : 'text'}
                    autoComplete={kind === 'secret' ? 'new-password' : 'off'}
                    data-form-type="other"
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder={kind === 'secret' ? ui(locale, '保存後は再表示されません', 'Never shown after saving') : 'production'}
                    className="h-10 rounded-lg border border-zinc-300 px-3 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </label>
                <button
                  type="submit"
                  disabled={saving}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-4 font-semibold text-white disabled:cursor-wait disabled:opacity-60 dark:bg-white dark:text-zinc-950"
                >
                  {saving && <HfIcon name="spinner" className="h-4 w-4 animate-spin" />}
                  {ui(locale, '保存／ローテーション', 'Save / rotate')}
                </button>
              </form>

              {notice && (
                <p
                  role={notice.kind === 'error' ? 'alert' : 'status'}
                  className={`rounded-lg px-3 py-2 text-sm ${
                    notice.kind === 'error'
                      ? 'bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300'
                      : 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300'
                  }`}
                >
                  {notice.text}
                </p>
              )}

              <div className="space-y-2" aria-busy={loading}>
                <h3 className="font-bold">{ui(locale, '設定済み', 'Configured')}</h3>
                {loading ? (
                  <p className="text-sm text-zinc-500">{ui(locale, '読み込み中…', 'Loading…')}</p>
                ) : items.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
                    {ui(locale, '設定はまだありません。', 'No settings yet.')}
                  </p>
                ) : (
                  items.map((item) => (
                    <div
                      key={item.name}
                      data-space-environment-name={item.name}
                      className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
                    >
                      <HfIcon name={item.kind === 'secret' ? 'key' : 'gear'} className="h-4 w-4 text-zinc-500" />
                      <div className="min-w-0 flex-1">
                        <p className="break-all font-mono text-sm font-bold">{item.name}</p>
                        <p className="truncate text-xs text-zinc-500">
                          {item.kind === 'secret' ? '••••••••' : item.value} · {item.scope} · {item.enabled ? ui(locale, '有効', 'enabled') : ui(locale, '無効', 'disabled')}
                        </p>
                      </div>
                      <div className="col-span-2 flex items-center justify-end gap-3 sm:col-span-1">
                        <span className="rounded-full bg-zinc-100 px-2 py-1 text-[11px] font-semibold uppercase text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                          {item.kind}
                        </span>
                        <button type="button" onClick={() => edit(item)} className="text-xs font-semibold text-blue-700 dark:text-blue-300">
                          {item.kind === 'secret' ? ui(locale, 'ローテーション', 'Rotate') : ui(locale, '編集', 'Edit')}
                        </button>
                        <button
                          type="button"
                          onClick={() => void setEnabled(item)}
                          disabled={saving}
                          className="text-xs font-semibold text-amber-700 disabled:opacity-50 dark:text-amber-300"
                        >
                          {item.enabled ? ui(locale, '無効化', 'Disable') : ui(locale, '有効化', 'Enable')}
                        </button>
                        <button
                          type="button"
                          onClick={() => void remove(item.name)}
                          disabled={saving}
                          className="text-xs font-semibold text-red-700 disabled:opacity-50 dark:text-red-300"
                        >
                          {pendingDelete === item.name ? ui(locale, '削除を確認', 'Confirm delete') : ui(locale, '削除', 'Delete')}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
