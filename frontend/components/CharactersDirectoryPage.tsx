import Link from 'next/link';
import { CharacterRepositoryProfile, CodexPetPackage, inspectCharacterRepository } from '@/lib/character-format';
import { forgejoRawUrl, nonTypeTopics } from '@/lib/forgejo';
import { getCatalogPage, isCatalogSort, isSortOrder, type CatalogSort, type RankedRepo, type SortOrder } from '@/lib/catalog-sort';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import HfIcon from './HfIcon';
import PuruPuruPreview from './PuruPuruPreview';
import CatalogSortControl from './CatalogSortControl';

type CharacterCatalogItem = {
  kind: 'purupuru' | 'pet' | 'sheets';
  id: string;
  title: string;
  description: string | null;
  href: string;
  repo: RankedRepo;
  profile: CharacterRepositoryProfile;
  pet?: CodexPetPackage;
  owner: string;
  branch: string;
  searchText: string;
};

export default async function CharactersDirectoryPage({
  searchParams,
}: {
  searchParams?: { q?: string; sort?: string; order?: string };
}) {
  const locale = await getLocale();
  const q = searchParams?.q?.trim() || undefined;
  const sort: CatalogSort = isCatalogSort(searchParams?.sort) ? searchParams.sort : 'updated';
  const order: SortOrder = isSortOrder(searchParams?.order) ? searchParams.order : 'desc';
  const result = await getCatalogPage({ topic: 'character', sort, order, page: 1, limit: 100 });
  const profiled = await Promise.all(result.data.map(async (repo) => ({
    repo,
    profile: await inspectCharacterRepository(repo),
  })));
  const allItems = profiled.flatMap<CharacterCatalogItem>(({ repo, profile }) => {
    const owner = repo.owner?.login || repo.full_name.split('/')[0];
    const branch = repo.default_branch || 'main';
    if (profile.purupuru) {
      return [{
        kind: 'purupuru' as const,
        id: repo.name,
        title: repo.name,
        description: repo.description,
        href: `/${owner}/${repo.name}`,
        repo,
        profile,
        owner,
        branch,
        searchText: `purupuru ${profile.purupuru.motionPatchPath ? 'head-motion motion-patch' : 'upper-body'} ${repo.topics?.join(' ') || ''}`,
      }];
    }
    const pet = profile.codexPet?.packages[0];
    if (pet) {
      return [{
        kind: 'pet' as const,
        id: pet.id,
        title: repo.name,
        description: ui(locale, `${pet.displayName}のインストール可能なCodex Petパッケージ`, `Installable Codex Pet package for ${pet.displayName}`),
        href: `/${owner}/${repo.name}`,
        repo,
        profile,
        pet,
        owner,
        branch,
        searchText: `codex-pet pet ${pet.id} ${pet.displayName} ${repo.topics?.join(' ') || ''}`,
      }];
    }
    if (profile.characterSheets) {
      return [{
        kind: 'sheets' as const,
        id: repo.name,
        title: repo.name,
        description: repo.description || ui(locale, '独立したキャラクター設定画リポジトリ', 'Independent character-sheet repository'),
        href: `/${owner}/${repo.name}`,
        repo,
        profile,
        owner,
        branch,
        searchText: `character-sheet design-sheet ${repo.topics?.join(' ') || ''}`,
      }];
    }
    return [];
  });
  const normalizedQuery = q?.toLocaleLowerCase();
  const catalogItems = normalizedQuery
    ? allItems.filter((item) => `${item.title} ${item.description || ''} ${item.repo.name} ${item.searchText}`.toLocaleLowerCase().includes(normalizedQuery))
    : allItems;
  const purupuruStates = profiled.reduce((total, item) => total + (item.profile.purupuru?.totalStates || 0), 0);
  const petPackages = profiled.reduce((total, item) => total + (item.profile.codexPet?.packageCount || 0), 0);
  const filters = [
    ['PuruPuru', 'purupuru'],
    ['Codex Pet', 'codex-pet'],
    [ui(locale, '頭部モーション', 'Head motion'), 'head-motion'],
    [ui(locale, 'キャラクターシート', 'Character sheets'), 'character-sheet'],
  ];

  return (
    <div className="mx-auto max-w-[1536px] px-4 pb-14">
      <section className="relative overflow-hidden border-b border-zinc-200 py-10 sm:py-14">
        <div className="pointer-events-none absolute -right-16 top-0 h-56 w-56 rounded-full bg-cyan-300/20 blur-3xl" />
        <div className="pointer-events-none absolute right-40 top-24 h-44 w-44 rounded-full bg-fuchsia-300/15 blur-3xl" />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-end">
          <div>
            <p className="flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.22em] text-fuchsia-700 dark:text-fuchsia-300">
              <span className="h-px w-8 bg-current" /> Character asset registry
            </p>
            <h1 className="mt-4 max-w-3xl text-4xl font-black tracking-tight text-zinc-950 sm:text-6xl dark:text-white">
              {ui(locale, '動くキャラクターを、規格ごと持ち運ぶ。', 'Portable characters, complete with their runtime format.')}
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-600 dark:text-zinc-300">
              {ui(locale, 'PuruPuru PNGtuber、方向制御パッチ、Codex Pet、キャラクターシートを同じGitリポジトリとして公開・検証できます。', 'Publish and verify PuruPuru PNGtubers, direction-control patches, Codex Pets, and character sheets as normal Git repositories.')}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-px overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-200 text-center dark:border-zinc-700 dark:bg-zinc-700">
            <div className="bg-white p-4 dark:bg-zinc-950"><strong className="block text-2xl">{allItems.length}</strong><span className="text-xs text-zinc-500">entries</span></div>
            <div className="bg-white p-4 dark:bg-zinc-950"><strong className="block text-2xl">{purupuruStates}</strong><span className="text-xs text-zinc-500">PuruPuru states</span></div>
            <div className="bg-white p-4 dark:bg-zinc-950"><strong className="block text-2xl">{petPackages}</strong><span className="text-xs text-zinc-500">pet packages</span></div>
          </div>
        </div>
      </section>

      <div className="flex flex-col gap-4 border-b border-zinc-200 py-5 lg:flex-row lg:items-center">
        <form action="/characters" method="get" className="relative w-full lg:max-w-sm">
          <input name="q" defaultValue={q} placeholder={ui(locale, '名前・規格・トピックを検索', 'Search names, formats, and topics')} className="h-11 w-full rounded-full border border-zinc-300 bg-white pl-11 pr-4 text-sm outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-900" />
          <HfIcon name="search" className="absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
          <input type="hidden" name="sort" value={sort} />
          <input type="hidden" name="order" value={order} />
        </form>
        <nav className="flex flex-wrap gap-2" aria-label={ui(locale, 'キャラクター形式', 'Character formats')}>
          {filters.map(([label, query]) => (
            <Link key={query} href={`/characters?${new URLSearchParams({ q: query, sort, order })}`} className="rounded-full border border-zinc-200 px-3 py-2 text-xs font-semibold text-zinc-600 hover:border-fuchsia-300 hover:text-fuchsia-800 dark:border-zinc-700 dark:text-zinc-300">
              {label}
            </Link>
          ))}
        </nav>
        <CatalogSortControl action="/characters" locale={locale} order={order} preserve={{ q }} sort={sort} />
        <Link href="/new?type=character" className="nyankoface-character-primary-action inline-flex h-10 items-center justify-center gap-2 rounded-full bg-zinc-950 px-4 text-sm font-bold text-white hover:bg-zinc-800 dark:bg-cyan-300 dark:text-zinc-950 dark:hover:bg-cyan-200">
          <HfIcon name="plus" className="h-3 w-3" /> {ui(locale, 'キャラクターを追加', 'Add character')}
        </Link>
      </div>

      {!result.ok ? (
        <div className="mt-8 rounded-xl border border-dashed border-zinc-300 p-10 text-center text-zinc-500">{ui(locale, 'Forgejoに接続できませんでした。', 'Could not connect to Forgejo.')}</div>
      ) : catalogItems.length === 0 ? (
        <div className="mt-8 rounded-xl border border-dashed border-zinc-300 p-10 text-center text-zinc-500">{ui(locale, 'キャラクターリポジトリはまだありません。', 'No character repositories yet.')}</div>
      ) : (
        <div className="mt-8 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {catalogItems.map((item) => {
            const { repo, profile, owner, branch } = item;
            const formatLabels = item.kind === 'purupuru'
              ? [`PuruPuru · ${profile.purupuru?.totalStates || 0} states`]
              : item.kind === 'pet'
                ? ['Codex Pet', item.pet?.atlasSize || profile.codexPet?.atlasSize || '']
                : [ui(locale, 'Character Sheet', 'Character Sheet')];
            const previewPath = item.kind === 'pet'
              ? item.pet?.previewPath
              : item.kind === 'sheets'
                ? profile.characterSheets?.previewPath
                : null;
            return (
              <article
                key={`${repo.full_name}:${item.kind}:${item.id}`}
                className="group overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm transition hover:-translate-y-1 hover:border-fuchsia-300 hover:shadow-xl dark:border-zinc-800 dark:bg-zinc-900"
                data-codex-pet-card={item.kind === 'pet' ? item.id : undefined}
              >
                <Link href={item.href} className="relative block aspect-[16/10] overflow-hidden bg-zinc-950">
                  <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(34,211,238,.25)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,.25)_1px,transparent_1px)] [background-size:22px_22px]" />
                  {item.kind === 'purupuru' && profile.purupuru?.frames.length ? (
                    <PuruPuruPreview
                      compact
                      locale={locale}
                      frames={profile.purupuru.frames.map((frame) => ({
                        ...frame,
                        src: forgejoRawUrl(owner, repo.name, frame.path, branch),
                      }))}
                    />
                  ) : previewPath ? (
                    <img
                      src={forgejoRawUrl(owner, repo.name, previewPath, branch)}
                      alt={item.kind === 'pet' ? `${item.title} pet preview` : `${item.title} preview`}
                      loading="eager"
                      className="relative h-full w-full object-contain p-3 transition duration-500 group-hover:scale-[1.03]"
                    />
                  ) : (
                    <span className="relative grid h-full place-items-center"><HfIcon name="character" className="h-14 w-14 text-cyan-300" /></span>
                  )}
                  <span className="absolute left-3 top-3 rounded-full bg-black/65 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wider text-cyan-200 backdrop-blur">
                    {formatLabels[0] || 'Character'}
                  </span>
                </Link>
                <div className="p-5">
                  <p className="font-mono text-xs text-zinc-500">{owner}/</p>
                  <Link href={item.href} className="mt-1 block break-words text-lg font-black tracking-tight text-zinc-950 hover:text-fuchsia-700 dark:text-white dark:hover:text-fuchsia-300">{item.title}</Link>
                  <p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-zinc-600 dark:text-zinc-400">{item.description}</p>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {formatLabels.map((label) => <span key={label} className="rounded-md bg-zinc-100 px-2 py-1 text-[11px] font-semibold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">{label}</span>)}
                    {item.kind === 'purupuru' && profile.purupuru?.motionPatchPath ? <span className="rounded-md bg-fuchsia-100 px-2 py-1 text-[11px] font-semibold text-fuchsia-800 dark:bg-fuchsia-950 dark:text-fuchsia-200">motion patch</span> : null}
                    {item.kind === 'pet' && item.pet?.qaPath ? <span className="rounded-md bg-cyan-100 px-2 py-1 text-[11px] font-semibold text-cyan-800 dark:bg-cyan-950 dark:text-cyan-200">QA verified</span> : null}
                  </div>
                  <div className="mt-5 flex items-center gap-3 border-t border-zinc-100 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
                    <span>{locale === 'ja' ? timeAgoJa(repo.updated_at) : timeAgoEn(repo.updated_at)}</span>
                    <span className="inline-flex items-center gap-1"><HfIcon name="heart" className="h-3 w-3" />{repo.metrics.availability === 'available' ? repo.metrics.likes : '—'}</span>
                    <span className="inline-flex items-center gap-1"><HfIcon name="eye" className="h-3 w-3" />{repo.metrics.availability === 'available' ? repo.metrics.views : '—'}</span>
                    <span className="ml-auto">{nonTypeTopics(repo.topics).slice(0, 2).join(' · ')}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
