import Link from 'next/link';
import { CharacterRepositoryProfile } from '@/lib/character-format';
import { forgejoRawUrl, forgejoTreeUrl } from '@/lib/forgejo';
import { Locale, ui } from '@/lib/i18n';
import HfIcon from './HfIcon';
import PuruPuruPreview from './PuruPuruPreview';

export default function CharacterRepositoryPanel({
  owner,
  repo,
  branch,
  profile,
  locale,
}: {
  owner: string;
  repo: string;
  branch: string;
  profile: CharacterRepositoryProfile;
  locale: Locale;
}) {
  const selectedPet = profile.codexPet?.packages[0] || null;
  const sheetDisplayName = repo
    .replace(/-character-sheet$/i, '')
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
  const panelTitle = selectedPet
    ? `${selectedPet.displayName} · Codex Pet`
    : profile.characterSheets
      ? `${sheetDisplayName} · ${ui(locale, 'キャラクターシート', 'Character Sheet')}`
      : ui(locale, 'PuruPuru実行形式', 'PuruPuru runtime format');
  const panelCopy = selectedPet
    ? ui(locale, 'pet.json、spritesheet、アニメーションフレーム、QA成果物をこのリポジトリだけで確認できます。', 'This repository contains its own pet.json, spritesheet, animation frames, and QA evidence.')
    : profile.characterSheets
      ? ui(locale, '設定画の書き出し画像、一覧用サムネイル、権利メタデータをこのリポジトリだけで確認できます。', 'This repository contains its own exported character sheet, catalog thumbnail, and rights metadata.')
      : ui(locale, '設定、状態画像、方向制御パッチを実ファイルから検出しました。', 'NyankoFace detected settings, state images, and the direction-control patch from real files.');
  const formats = [
    profile.purupuru ? {
      name: 'PuruPuru',
      detail: ui(locale, `${profile.purupuru.directions}方向・${profile.purupuru.totalStates}状態`, `${profile.purupuru.directions} directions · ${profile.purupuru.totalStates} states`),
      tone: 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-900 dark:border-fuchsia-900 dark:bg-fuchsia-950/30 dark:text-fuchsia-200',
    } : null,
    profile.codexPet ? {
      name: 'Codex Pet',
      detail: ui(locale, `独立パッケージ・${profile.codexPet.atlasSize}`, `Independent package · ${profile.codexPet.atlasSize}`),
      tone: 'border-cyan-200 bg-cyan-50 text-cyan-900 dark:border-cyan-900 dark:bg-cyan-950/30 dark:text-cyan-200',
    } : null,
    profile.characterSheets ? {
      name: ui(locale, 'キャラクターシート', 'Character sheets'),
      detail: ui(locale, '独立リポジトリ', 'Independent repository'),
      tone: 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200',
    } : null,
  ].filter((format): format is NonNullable<typeof format> => Boolean(format));

  if (formats.length === 0) return null;

  return (
    <section className="nyankoface-character-format-panel mb-7 overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-950 text-white shadow-sm dark:border-zinc-700">
      <div className="grid lg:grid-cols-[minmax(0,1.3fr)_minmax(280px,.7fr)]">
        <div className="relative min-h-72 overflow-hidden bg-[radial-gradient(circle_at_20%_10%,rgba(34,211,238,.24),transparent_38%),radial-gradient(circle_at_90%_90%,rgba(217,70,239,.18),transparent_35%),linear-gradient(145deg,#09090b,#18181b)]">
          <div className="absolute inset-0 opacity-20 [background-image:linear-gradient(rgba(255,255,255,.12)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.12)_1px,transparent_1px)] [background-size:24px_24px]" />
          {profile.purupuru?.frames.length ? (
            <PuruPuruPreview
              frames={profile.purupuru.frames.map((frame) => ({
                ...frame,
                src: forgejoRawUrl(owner, repo, frame.path, branch),
              }))}
              locale={locale}
            />
          ) : selectedPet?.previewPath ? (
            <img
              src={forgejoRawUrl(owner, repo, selectedPet.previewPath, branch)}
              alt={ui(locale, `${selectedPet.displayName}のCodex Petアニメーションプレビュー`, `${selectedPet.displayName} Codex Pet animation preview`)}
              className="relative h-full max-h-[440px] min-h-72 w-full object-contain p-5"
            />
          ) : profile.previewPath ? (
            <img
              src={forgejoRawUrl(owner, repo, profile.previewPath, branch)}
              alt={ui(locale, `${repo}のキャラクタープレビュー`, `${repo} character preview`)}
              className="relative h-full max-h-[440px] w-full object-contain p-5"
            />
          ) : (
            <div className="relative grid min-h-72 place-items-center"><HfIcon name="character" className="h-16 w-16 text-cyan-300" /></div>
          )}
        </div>
        <div className="flex flex-col border-t border-white/10 p-6 lg:border-l lg:border-t-0">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.22em] text-cyan-300">{ui(locale, '検出済み規格', 'Detected formats')}</p>
          <h2 className="mt-3 text-2xl font-extrabold tracking-tight">{panelTitle}</h2>
          <p className="nyankoface-character-panel-copy mt-3 text-sm leading-6 text-zinc-300">{panelCopy}</p>
          <div className="mt-5 grid gap-2">
            {formats.map((format) => (
              <div key={format.name} className={`rounded-xl border px-3 py-2.5 ${format.tone}`}>
                <p className="text-sm font-bold">{format.name}</p>
                <p className="mt-0.5 text-xs opacity-75">{format.detail}</p>
              </div>
            ))}
          </div>
          {profile.purupuru ? (
            <div className="mt-4 grid gap-2 text-xs">
              <Link href={forgejoTreeUrl(owner, repo, profile.purupuru.settingsPath, branch)} className="rounded-lg border border-white/15 px-3 py-2 hover:bg-white/5">
                avatar/default-settings.json
              </Link>
              {profile.purupuru.motionPatchPath ? (
                <Link href={forgejoTreeUrl(owner, repo, profile.purupuru.motionPatchPath, branch)} className="inline-flex items-center gap-2 rounded-lg border border-fuchsia-400/30 px-3 py-2 font-semibold text-fuchsia-300 hover:bg-fuchsia-400/10">
                  <HfIcon name="download" className="h-3.5 w-3.5" /> PuruPuru direction-control patch
                </Link>
              ) : null}
            </div>
          ) : null}
          {profile.codexPet ? (
            selectedPet ? (
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <Link href={forgejoTreeUrl(owner, repo, selectedPet.petJsonPath, branch)} className="rounded-lg border border-white/15 px-3 py-2 hover:bg-white/5">pet.json</Link>
                <Link href={forgejoTreeUrl(owner, repo, selectedPet.spritesheetPath, branch)} className="rounded-lg border border-white/15 px-3 py-2 hover:bg-white/5">spritesheet.webp</Link>
              </div>
            ) : null
          ) : null}
          {profile.characterSheets ? (
            <div className="mt-4 text-xs">
              <Link
                href={forgejoTreeUrl(owner, repo, profile.characterSheets.catalogPath, branch)}
                className="block rounded-lg border border-white/15 px-3 py-2 hover:bg-white/5"
              >
                metadata/characters.csv
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
