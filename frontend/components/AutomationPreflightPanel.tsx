'use client';

import { useState } from 'react';
import type { AutomationPreflight } from '@/lib/automation';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

export default function AutomationPreflightPanel({
  owner,
  repo,
  preflight,
  reviewedToml,
}: {
  owner: string;
  repo: string;
  preflight: AutomationPreflight;
  reviewedToml: string | null;
}) {
  const { locale } = useLocale();
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState<'copy' | 'download' | null>(null);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState('');
  const warnings = preflight.findings.filter((item) => item.severity === 'warning');
  const errors = preflight.findings.filter((item) => item.severity === 'error');
  const canPrepare = preflight.ok && reviewedToml && (!warnings.length || acknowledged);
  const config = preflight.config;

  const requestBundle = async (downloadId?: string): Promise<Blob | null> => {
    const response = await fetch(`/api/automations/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/bundle`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: preflight.source?.sha,
        acknowledgeWarnings: acknowledged,
        ...(downloadId ? { downloadId } : {}),
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { error?: string } | null;
      setMessage(payload?.error || ui(locale, '設定を準備できませんでした。', 'Could not prepare the configuration.'));
      return null;
    }
    return response.blob();
  };

  const copyBundle = async () => {
    if (!canPrepare) return;
    setBusy('copy');
    setMessage('');
    try {
      const blob = await requestBundle();
      if (!blob) return;
      await navigator.clipboard.writeText(await blob.text());
      setCopied(true);
      setMessage(ui(locale, '無効化済みTOMLをコピーしました。', 'Copied the disabled TOML.'));
      window.setTimeout(() => setCopied(false), 1800);
    } finally {
      setBusy(null);
    }
  };

  const downloadBundle = async () => {
    if (!canPrepare) return;
    setBusy('download');
    setMessage('');
    try {
      const downloadId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      const blob = await requestBundle(downloadId);
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${repo}-automation.toml`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage(ui(locale, '無効化済みTOMLをダウンロードしました。', 'Downloaded the disabled TOML.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="nyankoface-automation-preflight mb-8 overflow-hidden rounded-2xl border border-amber-200 bg-[#fffdf6] shadow-[0_18px_55px_-38px_rgba(120,79,20,0.45)] dark:border-amber-900/70 dark:bg-[#15130d]" data-automation-preflight>
      <div className="nyankoface-automation-header border-b border-amber-200/80 bg-[linear-gradient(120deg,rgba(251,191,36,0.14),transparent_52%)] px-5 py-5 sm:px-6 dark:border-amber-900/60">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-amber-950 text-amber-100 shadow-sm dark:bg-amber-300 dark:text-amber-950">
              <HfIcon name="automation" className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-amber-800 dark:text-amber-300">Automation preflight</p>
              <h2 className="mt-1 text-xl font-bold tracking-tight text-zinc-950 dark:text-zinc-50">
                {ui(locale, '実行前に、設定の境界を確認', 'Review the configuration boundary before use')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
                {ui(locale, '閲覧だけでは登録・実行されません。ダウンロードされる設定は必ず無効状態です。', 'Browsing never registers or runs this Automation. Every downloaded configuration remains disabled.')}
              </p>
            </div>
          </div>
          <div
            className={`nyankoface-automation-status inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ${preflight.ok ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'}`}
            data-state={preflight.ok ? 'passed' : 'blocked'}
          >
            <span className={`h-2 w-2 rounded-full ${preflight.ok ? 'bg-emerald-500' : 'bg-rose-500'}`} />
            {preflight.ok ? ui(locale, '検査済み', 'Preflight passed') : ui(locale, '修正が必要', 'Blocked')}
          </div>
        </div>
      </div>

      {config ? (
        <div className="nyankoface-automation-metrics grid gap-px border-b border-amber-200/80 bg-amber-200/70 sm:grid-cols-2 lg:grid-cols-4 dark:border-amber-900/60 dark:bg-amber-900/50">
          {[
            [ui(locale, 'スケジュール', 'Schedule'), `${config.schedule_type} · ${config.timezone}`],
            [ui(locale, 'ワークスペース', 'Workspace'), config.workspace_required ? ui(locale, '必要', 'Required') : ui(locale, '不要', 'Not required')],
            [ui(locale, '配信', 'Delivery'), config.delivery_type],
            [ui(locale, '互換性', 'Compatibility'), preflight.compatible ? `${config.platform} · schema ${config.schema_version}` : ui(locale, '要確認', 'Review required')],
          ].map(([label, value]) => (
            <div key={label} className="nyankoface-automation-metric bg-[#fffdf6] px-5 py-4 dark:bg-[#15130d]">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-zinc-400">{label}</p>
              <p className="mt-1 truncate text-sm font-semibold text-zinc-800 dark:text-zinc-200" title={value}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <div className="grid gap-5 sm:grid-cols-2">
            <ManifestList title={ui(locale, '要求権限', 'Required permissions')} values={config?.required_permissions || []} empty={ui(locale, '権限なし', 'No permissions')} />
            <ManifestList title={ui(locale, 'コネクター', 'Connectors')} values={config?.required_connectors || []} empty={ui(locale, 'コネクターなし', 'No connectors')} />
          </div>

          {preflight.findings.length ? (
            <div className="mt-6 space-y-2" data-automation-findings>
              {preflight.findings.map((item) => (
                <div key={`${item.code}-${item.path}`} className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${item.severity === 'error' ? 'border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200' : 'border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-200'}`}>
                  <HfIcon name={item.severity === 'error' ? 'key' : 'clock'} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <div>
                    <p className="font-semibold">{item.message}</p>
                    <p className="mt-0.5 font-mono text-[11px] opacity-65">{item.path} · {item.code}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-6 flex items-center gap-2 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
              <HfIcon name="check" className="h-3.5 w-3.5" />
              {ui(locale, 'スキーマと公開安全性の検査に合格しました。', 'Schema and publication safety checks passed.')}
            </div>
          )}

          {warnings.length ? (
            <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-xl border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
              <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} className="mt-0.5 h-4 w-4 accent-amber-700" />
              <span>{ui(locale, `${warnings.length}件の警告を確認し、無効状態の設定として取得します。`, `I reviewed ${warnings.length} warning${warnings.length === 1 ? '' : 's'} and will keep the downloaded configuration disabled.`)}</span>
            </label>
          ) : null}
        </div>

        <aside className="nyankoface-automation-source rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-zinc-400">{ui(locale, '検査対象', 'Reviewed source')}</p>
          <p className="mt-2 break-all font-mono text-xs font-semibold text-zinc-700 dark:text-zinc-300">{owner}/{repo}</p>
          <dl className="mt-4 space-y-3 text-xs">
            <div><dt className="text-zinc-400">Ref</dt><dd className="mt-0.5 truncate font-mono text-zinc-700 dark:text-zinc-300">{preflight.source?.ref || '—'}</dd></div>
            <div><dt className="text-zinc-400">Commit SHA</dt><dd className="mt-0.5 break-all font-mono text-zinc-700 dark:text-zinc-300">{preflight.source?.sha || '—'}</dd></div>
            <div><dt className="text-zinc-400">SHA-256</dt><dd className="mt-0.5 break-all font-mono text-zinc-700 dark:text-zinc-300">{preflight.sourceHash}</dd></div>
            <div><dt className="text-zinc-400">{ui(locale, '初期状態', 'Initial state')}</dt><dd className="mt-0.5 font-bold text-emerald-700 dark:text-emerald-300">disabled</dd></div>
          </dl>
          <div className="mt-5 grid gap-2">
            <button type="button" onClick={copyBundle} disabled={!canPrepare || busy !== null} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900">
              <HfIcon name={copied ? 'check' : 'copy'} className="h-3.5 w-3.5" />
              {busy === 'copy' ? ui(locale, '準備中…', 'Preparing…') : ui(locale, '無効TOMLをコピー', 'Copy disabled TOML')}
            </button>
            <button type="button" onClick={downloadBundle} disabled={!canPrepare || busy !== null} className="nyankoface-automation-primary inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-amber-950 px-3 text-sm font-semibold text-white transition hover:bg-amber-900 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-amber-300 dark:text-amber-950 dark:hover:bg-amber-200">
              <HfIcon name="download" className="h-3.5 w-3.5" />
              {busy === 'download' ? ui(locale, '準備中…', 'Preparing…') : ui(locale, '安全な設定を取得', 'Download reviewed config')}
            </button>
          </div>
          {message ? <p className="mt-3 text-xs leading-5 text-zinc-500" role="status">{message}</p> : null}
          {errors.length ? <p className="mt-3 text-xs leading-5 text-rose-700 dark:text-rose-300">{ui(locale, `${errors.length}件のエラーを解消すると取得できます。`, `Resolve ${errors.length} error${errors.length === 1 ? '' : 's'} before downloading.`)}</p> : null}
        </aside>
      </div>
    </section>
  );
}

function ManifestList({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return (
    <div>
      <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {values.length ? values.map((value) => (
          <span key={value} className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 font-mono text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">{value}</span>
        )) : <span className="text-sm text-zinc-400">{empty}</span>}
      </div>
    </div>
  );
}
