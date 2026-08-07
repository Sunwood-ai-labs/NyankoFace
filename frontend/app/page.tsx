import Link from 'next/link';
import BrandMark from '@/components/BrandMark';
import { searchRepos } from '@/lib/forgejo';
import HfIcon from '@/components/HfIcon';
import RepoGrid from '@/components/RepoGrid';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import { getLocale } from '@/lib/i18n-server';
import { Locale, ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';
import { getHomePagesPreview } from '@/lib/pages-discovery';
import HomePagesShowcase from '@/components/HomePagesShowcase';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: ui(locale, `${appName} - AIコンテンツを見つけ、作り、公開する`, `${appName} - Find, build, and publish AI content`),
    description: ui(locale, 'アプリ、Pages、ナレッジ、モデル、データ、エージェントツールをGitで管理・実行・共有できるAIプラットフォーム。', 'An AI platform for managing, running, and sharing apps, Pages, knowledge, models, data, and agent tools in Git.'),
  };
}

function CompactRepoList({
  repos,
  href,
  label,
  locale,
}: {
  repos: Awaited<ReturnType<typeof searchRepos>>['data'];
  href: string;
  label: string;
  locale: Locale;
}) {
  const kind = label === 'Models' ? 'model' : label === 'Datasets' ? 'dataset' : label === 'Skills' ? 'skill' : label === 'MCPs' ? 'mcp' : label === 'Prompts' ? 'prompt' : label === 'Docs' ? 'doc' : label === 'Characters' ? 'character' : label === 'Benchmarks' ? 'benchmark' : 'space';
  const theme = {
    model: {
      shell: 'border-zinc-200 bg-white',
      icon: 'bg-amber-100 text-amber-700 ring-amber-200',
      link: 'hover:bg-zinc-50',
      dot: 'bg-amber-400',
      browse: 'text-amber-700 hover:text-amber-900',
      title: 'text-amber-800',
    },
    space: {
      shell: 'border-indigo-200/80 bg-gradient-to-b from-indigo-50/80 via-white to-white shadow-indigo-100/60',
      icon: 'bg-indigo-100 text-indigo-700 ring-indigo-200',
      link: 'hover:bg-indigo-50/80',
      dot: 'bg-indigo-500',
      browse: 'text-indigo-700 hover:text-indigo-900',
      title: 'text-indigo-800',
    },
    dataset: {
      shell: 'border-zinc-200 bg-white',
      icon: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
      link: 'hover:bg-zinc-50',
      dot: 'bg-emerald-500',
      browse: 'text-emerald-700 hover:text-emerald-900',
      title: 'text-emerald-800',
    },
    skill: {
      shell: 'border-violet-200/80 bg-gradient-to-b from-violet-50/70 via-white to-white shadow-violet-100/60',
      icon: 'bg-violet-100 text-violet-700 ring-violet-200',
      link: 'hover:bg-violet-50/80',
      dot: 'bg-violet-500',
      browse: 'text-violet-700 hover:text-violet-900',
      title: 'text-violet-800',
    },
    mcp: {
      shell: 'border-cyan-200/80 bg-gradient-to-b from-cyan-50/70 via-white to-white shadow-cyan-100/60',
      icon: 'bg-cyan-100 text-cyan-700 ring-cyan-200',
      link: 'hover:bg-cyan-50/80',
      dot: 'bg-cyan-500',
      browse: 'text-cyan-700 hover:text-cyan-900',
      title: 'text-cyan-800',
    },
    prompt: {
      shell: 'border-orange-200/80 bg-gradient-to-b from-orange-50/80 via-white to-white shadow-orange-100/60',
      icon: 'bg-orange-100 text-orange-700 ring-orange-200',
      link: 'hover:bg-orange-50/80',
      dot: 'bg-orange-500',
      browse: 'text-orange-700 hover:text-orange-900',
      title: 'text-orange-800',
    },
    doc: {
      shell: 'border-teal-200/80 bg-gradient-to-b from-teal-50/80 via-white to-white shadow-teal-100/60',
      icon: 'bg-teal-100 text-teal-800 ring-teal-200',
      link: 'hover:bg-teal-50/80',
      dot: 'bg-teal-700',
      browse: 'text-teal-800 hover:text-teal-950 dark:text-teal-300 dark:hover:text-teal-200',
      title: 'text-teal-900',
    },
    character: {
      shell: 'border-fuchsia-200/80 bg-gradient-to-b from-fuchsia-50/70 via-white to-white shadow-fuchsia-100/60',
      icon: 'bg-fuchsia-100 text-fuchsia-800 ring-fuchsia-200',
      link: 'hover:bg-fuchsia-50/80',
      dot: 'bg-fuchsia-500',
      browse: 'text-fuchsia-800 hover:text-fuchsia-950 dark:text-fuchsia-300 dark:hover:text-fuchsia-200',
      title: 'text-fuchsia-900',
    },
    benchmark: {
      shell: 'border-sky-200/80 bg-gradient-to-b from-sky-50/80 via-white to-white shadow-sky-100/60',
      icon: 'bg-sky-100 text-sky-800 ring-sky-200',
      link: 'hover:bg-sky-50/80',
      dot: 'bg-sky-500',
      browse: 'text-sky-800 hover:text-sky-950 dark:text-sky-300 dark:hover:text-sky-200',
      title: 'text-sky-900',
    },
  }[kind];
  const displayLabel = ({ Models: 'モデル', Datasets: 'データセット', Spaces: 'Spaces', Skills: 'スキル', MCPs: 'MCPs', Prompts: 'プロンプト', Docs: 'ナレッジ', Characters: 'キャラクター', Benchmarks: 'ベンチマーク' } as Record<string, string>)[label] || label;

  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-bold text-zinc-950">
          <span className={`flex h-8 w-8 items-center justify-center rounded-lg ring-1 ${theme.icon}`}>
            <HfIcon name={kind} className="h-3.5 w-3.5" />
          </span>
          {ui(locale, displayLabel, label)}
        </h2>
        <Link href={href} className={`shrink-0 text-sm font-semibold hover:underline ${theme.browse}`}>
          {ui(locale, 'すべて見る', 'Browse all')}
        </Link>
      </div>
      <div className={`divide-y divide-zinc-100 overflow-hidden rounded-xl border shadow-sm ${theme.shell}`}>
        {repos.slice(0, 5).map((repo) => {
          const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
          return (
            <Link key={repo.id ?? repo.full_name} href={`/${owner}/${repo.name}`} className={`group flex gap-3 px-4 py-3 transition-colors ${theme.link}`}>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${theme.dot} transition-transform group-hover:scale-125`} />
              <div className="min-w-0">
                <p className={`truncate font-mono text-sm font-semibold group-hover:underline ${theme.title}`}>{repo.full_name}</p>
                <p className="mt-1 truncate text-xs text-zinc-500">
                  {ui(locale, `更新 ${timeAgoJa(repo.updated_at)}`, `Updated ${timeAgoEn(repo.updated_at)}`)} · {repo.description || ui(locale, '説明はありません', 'No description')}
                </p>
              </div>
            </Link>
          );
        })}
        {repos.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-zinc-500">{ui(locale, 'リポジトリはまだありません。', 'No repositories yet.')}</div>
        ) : null}
      </div>
    </section>
  );
}

export default async function HomePage() {
  const locale = await getLocale();
  const appName = getAppName();
  const [models, datasets, spaces, skills, mcps, prompts, docs, characters, benchmarks, pages] = await Promise.all([
    searchRepos({ topic: 'model', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'dataset', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'space', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'skill', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'mcp', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'prompt', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'doc', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'character', sort: 'updated', limit: 8 }),
    searchRepos({ topic: 'benchmark', sort: 'updated', limit: 8 }),
    getHomePagesPreview(),
  ]);

  return (
    <div>
      <section data-home-hero="classic" className="mx-auto max-w-5xl pb-8 pt-8 text-center sm:pt-10">
        <BrandMark className="mx-auto mb-5 h-14 w-14 rounded-[15px]" />
        <h1 className="mx-auto max-w-3xl text-3xl font-extrabold leading-tight tracking-normal text-zinc-950 dark:text-zinc-100 sm:text-4xl">
          {locale === 'ja' ? (
            <>
              <span className="sm:hidden">
                AIを見つける。試す。
                <br />
                作る。公開する。
              </span>
              <span className="hidden sm:inline">AIを見つける。試す。作る。公開する。</span>
            </>
          ) : (
            'Find it. Run it. Build it. Publish it.'
          )}
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-zinc-500 dark:text-zinc-400">
          {ui(
            locale,
            `${appName}は、アプリ、Pages、ナレッジ、モデル、データ、エージェントツールをGitで管理し、チームで実行・共有できるAIコンテンツプラットフォームです。`,
            `${appName} is an AI content platform where teams manage apps, Pages, knowledge, models, data, and agent tools in Git—then run and share them.`,
          )}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm">
          <Link href="/spaces" className="inline-flex h-10 items-center rounded-full border border-zinc-300 bg-white px-5 font-semibold text-zinc-950 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800">
            {ui(locale, 'AIアプリを見る', 'Explore AI Apps')}
          </Link>
          <span className="text-zinc-400">{ui(locale, 'または', 'or')}</span>
          <Link href="/models" className="inline-flex h-10 items-center font-semibold text-zinc-700 underline decoration-zinc-200 underline-offset-8 hover:text-zinc-950 dark:text-zinc-300 dark:decoration-zinc-700 dark:hover:text-white">
            {ui(locale, 'モデルを見る', 'Browse models')}
          </Link>
        </div>
      </section>

      <HomePagesShowcase preview={pages} locale={locale} />

      <section className="mx-auto mb-12 grid max-w-[1180px] gap-6 border-y border-zinc-200 py-8 lg:grid-cols-[0.72fr_1.28fr] lg:items-center">
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-fuchsia-700 dark:text-fuchsia-300">PuruPuru · Codex Pet</p>
          <h2 className="mt-3 font-serif text-4xl leading-none text-zinc-950 dark:text-white">{ui(locale, 'キャラクターも、実行形式ごと共有。', 'Share characters with their runtime format.')}</h2>
          <p className="mt-4 max-w-lg text-sm leading-6 text-zinc-600 dark:text-zinc-300">{ui(locale, '正面表情、方向別状態、PuruPuruパッチ、pet.json、spritesheet、QA結果をひとつのGit履歴で管理します。', 'Keep frontal expressions, directional states, PuruPuru patches, pet.json, spritesheets, and QA evidence in one Git history.')}</p>
          <Link href="/characters" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-fuchsia-900 hover:underline dark:text-fuchsia-300">{ui(locale, 'キャラクターを見る', 'Browse characters')} <HfIcon name="arrowRight" className="h-3 w-3" /></Link>
        </div>
        <CompactRepoList repos={characters.data} href="/characters" label="Characters" locale={locale} />
      </section>

      <section className="mx-auto mb-12 grid max-w-[1180px] gap-6 border-y border-zinc-200 py-8 lg:grid-cols-[0.72fr_1.28fr] lg:items-center">
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-orange-700">{ui(locale, '育つナレッジ', 'Living knowledge')}</p>
          <h2 className="mt-3 font-serif text-4xl leading-none text-zinc-950">{ui(locale, 'ナレッジもコミュニティの一部です。', 'Knowledge is part of the community.')}</h2>
          <p className="mt-4 max-w-lg text-sm leading-6 text-zinc-600">{ui(locale, 'すべての記事を通常のForgejoリポジトリとして公開し、タグでニュース、手順、参照情報、調査などに整理できます。', 'Publish every article from a normal Forgejo repository and organize news, how-to, reference, and research content with tags.')}</p>
          <Link href="/docs" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-teal-900 hover:underline dark:text-teal-300">{ui(locale, 'ライブラリを開く', 'Enter the library')} <HfIcon name="arrowRight" className="h-3 w-3" /></Link>
        </div>
        <CompactRepoList repos={docs.data} href="/docs" label="Docs" locale={locale} />
      </section>

      <section className="mx-auto mb-12 grid max-w-[1180px] gap-6 border-y border-sky-200 py-8 lg:grid-cols-[0.72fr_1.28fr] lg:items-center">
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-sky-700 dark:text-sky-300">Evaluation lab · Reproducible</p>
          <h2 className="mt-3 font-serif text-4xl leading-none text-zinc-950 dark:text-white">{ui(locale, '生成AIを、再現可能な基準で測る。', 'Measure generative AI with reproducible benchmarks.')}</h2>
          <p className="mt-4 max-w-lg text-sm leading-6 text-zinc-600 dark:text-zinc-300">{ui(locale, 'CADの実行可能テストやSVGの理解・編集・生成を、課題、実行コード、評価指標、結果と一緒にGitで共有します。', 'Share CAD executable tests and SVG understanding, editing, and generation with tasks, runners, metrics, and results in Git.')}</p>
          <Link href="/benchmarks" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-sky-900 hover:underline dark:text-sky-300">{ui(locale, '評価ラボを開く', 'Open the evaluation lab')} <HfIcon name="arrowRight" className="h-3 w-3" /></Link>
        </div>
        <CompactRepoList repos={benchmarks.data} href="/benchmarks" label="Benchmarks" locale={locale} />
      </section>

      <section className="mx-auto mb-12 max-w-[1180px]">
        <div className="mb-5 flex items-center justify-center gap-4 text-lg font-bold text-zinc-950">
          <span className="h-px w-24 bg-violet-200" />
          <span>{ui(locale, 'エージェントツール', 'Agent tooling')}</span>
          <span className="h-px w-24 bg-cyan-200" />
        </div>
        <div className="grid gap-5 lg:grid-cols-3">
          <CompactRepoList repos={skills.data} href="/skills" label="Skills" locale={locale} />
          <CompactRepoList repos={mcps.data} href="/mcps" label="MCPs" locale={locale} />
          <CompactRepoList repos={prompts.data} href="/prompts" label="Prompts" locale={locale} />
        </div>
      </section>

      <section className="mx-auto mb-12 max-w-[1180px]">
        <div className="mb-5 flex items-center justify-center gap-4 text-lg font-bold text-zinc-950">
          <span className="h-px w-24 bg-zinc-200" />
          <span>{ui(locale, `今週の${appName}トレンド`, `Trending on ${appName} this week`)}</span>
          <span className="h-px w-24 bg-zinc-200" />
        </div>
        <div className="grid gap-5 lg:grid-cols-3">
          <CompactRepoList repos={models.data} href="/models" label="Models" locale={locale} />
          <CompactRepoList repos={spaces.data} href="/spaces" label="Spaces" locale={locale} />
          <CompactRepoList repos={datasets.data} href="/datasets" label="Datasets" locale={locale} />
        </div>
      </section>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-xl font-bold text-zinc-950">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 text-amber-700 ring-1 ring-amber-200">
              <HfIcon name="model" className="h-3.5 w-3.5" />
            </span>
            {ui(locale, '最新モデル', 'Latest models')}
          </h2>
          <Link href="/models" className="inline-flex items-center gap-1 text-sm font-semibold text-zinc-600 hover:text-zinc-950 hover:underline">
            {ui(locale, 'すべて見る', 'Browse all')} <HfIcon name="arrowRight" className="h-3 w-3" />
          </Link>
        </div>
        <RepoGrid repos={models.data} kind="model" emptyMessage={ui(locale, 'モデルはまだありません。', 'No models yet.')} locale={locale} />
      </section>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-xl font-bold text-zinc-950">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100 text-indigo-700 ring-1 ring-indigo-200">
              <HfIcon name="space" className="h-3.5 w-3.5" />
            </span>
            Spaces
          </h2>
          <Link href="/spaces" className="inline-flex items-center gap-1 text-sm font-semibold text-zinc-600 hover:text-zinc-950 hover:underline">
            {ui(locale, 'すべて見る', 'Browse all')} <HfIcon name="arrowRight" className="h-3 w-3" />
          </Link>
        </div>
        <RepoGrid repos={spaces.data} kind="space" emptyMessage={ui(locale, 'Spaceはまだありません。', 'No Spaces yet.')} locale={locale} />
      </section>

      <section className="mb-14">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-xl font-bold text-zinc-950">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200">
              <HfIcon name="dataset" className="h-3.5 w-3.5" />
            </span>
            {ui(locale, 'データセット', 'Datasets')}
          </h2>
          <Link href="/datasets" className="inline-flex items-center gap-1 text-sm font-semibold text-zinc-600 hover:text-zinc-950 hover:underline">
            {ui(locale, 'すべて見る', 'Browse all')} <HfIcon name="arrowRight" className="h-3 w-3" />
          </Link>
        </div>
        <RepoGrid repos={datasets.data} kind="dataset" emptyMessage={ui(locale, 'データセットはまだありません。', 'No datasets yet.')} locale={locale} />
      </section>

    </div>
  );
}
