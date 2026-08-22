import HfIcon, { HfIconName } from '@/components/HfIcon';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  return { title: `${ui(locale, '新しいリポジトリ', 'New repository')} - ${getAppName()}` };
}

const repoTypes: Array<{
  label: string;
  labelJa: string;
  topic: string;
  icon: HfIconName;
  description: string;
  descriptionJa: string;
}> = [
  {
    label: 'Model',
    labelJa: 'モデル',
    topic: 'model',
    icon: 'model',
    description: 'Weights, configs, tokenizer files, and a model card.',
    descriptionJa: '重み、設定、トークナイザー、モデルカードを管理します。',
  },
  {
    label: 'Dataset',
    labelJa: 'データセット',
    topic: 'dataset',
    icon: 'dataset',
    description: 'Data files, dataset_infos, splits, and dataset cards.',
    descriptionJa: 'データファイル、分割情報、データセットカードを管理します。',
  },
  {
    label: 'Space',
    labelJa: 'Space',
    topic: 'space',
    icon: 'space',
    description: 'Interactive apps backed by Gradio, Docker, or static files.',
    descriptionJa: 'Gradio、Docker、静的ファイルで動く対話型アプリです。',
  },
  {
    label: 'Skill',
    labelJa: 'スキル',
    topic: 'skill',
    icon: 'skill',
    description: 'Reusable agent instructions centered on a SKILL.md file.',
    descriptionJa: 'SKILL.mdを中心とした再利用可能なエージェント指示です。',
  },
  {
    label: 'MCP server',
    labelJa: 'MCPサーバー',
    topic: 'mcp',
    icon: 'mcp',
    description: 'Tools and resources exposed through Model Context Protocol.',
    descriptionJa: 'Model Context Protocol経由でツールとリソースを公開します。',
  },
  {
    label: 'Prompt',
    labelJa: 'プロンプト',
    topic: 'prompt',
    icon: 'prompt',
    description: 'Versioned instructions for agents, workflows, and reusable commands.',
    descriptionJa: 'エージェント、ワークフロー、再利用コマンド向けの版管理された指示です。',
  },
  {
    label: 'Doc',
    labelJa: 'ナレッジ',
    topic: 'doc',
    icon: 'doc',
    description: 'One personal or team publication containing many Markdown entries.',
    descriptionJa: '個人またはチームの記事をまとめるMarkdown出版リポジトリです。',
  },
  {
    label: 'Character',
    labelJa: 'キャラクター',
    topic: 'character',
    icon: 'character',
    description: 'PuruPuru PNGtubers, Codex Pets, character sheets, and their QA evidence.',
    descriptionJa: 'PuruPuru PNGtuber、Codex Pet、キャラクターシート、QA証跡を管理します。',
  },
  {
    label: 'Benchmark',
    labelJa: 'ベンチマーク',
    topic: 'benchmark',
    icon: 'benchmark',
    description: 'Reproducible evaluation suites, task data, runners, and result reports.',
    descriptionJa: '再現可能な評価スイート、課題データ、実行環境、結果レポートを管理します。',
  },
  {
    label: 'Automation',
    labelJa: 'Automation',
    topic: 'automation',
    icon: 'automation',
    description: 'Portable, versioned Codex schedules with explicit permissions and safe preflight.',
    descriptionJa: '権限と安全性を事前確認できる、持ち運び可能なCodexスケジュールです。',
  },
];

const templates = [
  { label: 'Gradio app', labelJa: 'Gradioアプリ', topic: 'space', repo: 'my-gradio-space', slug: 'gradio-app' },
  { label: 'Docker Space', labelJa: 'Docker Space', topic: 'space', repo: 'my-docker-space', slug: 'docker-space' },
  { label: 'Model card', labelJa: 'モデルカード', topic: 'model', repo: 'my-model', slug: 'model-card' },
  { label: 'Dataset card', labelJa: 'データセットカード', topic: 'dataset', repo: 'my-dataset', slug: 'dataset-card' },
  { label: 'Agent Skill', labelJa: 'エージェントスキル', topic: 'skill', repo: 'my-agent-skill', slug: 'agent-skill' },
  { label: 'MCP server', labelJa: 'MCPサーバー', topic: 'mcp', repo: 'my-mcp-server', slug: 'mcp-server' },
  { label: 'Versioned prompt', labelJa: '版管理プロンプト', topic: 'prompt', repo: 'my-agent-prompt', slug: 'versioned-prompt' },
  { label: 'Knowledge publication', labelJa: 'ナレッジ出版', topic: 'doc', repo: 'my-knowledge', slug: 'documentation' },
  { label: 'Thread knowledge', labelJa: 'スレッド解説ナレッジ', topic: 'doc', repo: 'my-thread-knowledge', slug: 'thread-knowledge' },
  { label: 'PuruPuru PNGtuber', labelJa: 'PuruPuru PNGtuber', topic: 'character', repo: 'my-purupuru-character', slug: 'purupuru-pngtuber' },
  { label: 'Codex Pet package', labelJa: 'Codex Petパッケージ', topic: 'character', repo: 'my-codex-pet', slug: 'codex-pet' },
  { label: 'Character sheets', labelJa: 'キャラクターシート集', topic: 'character', repo: 'my-character-sheets', slug: 'character-sheets' },
  { label: 'Benchmark suite', labelJa: 'ベンチマークスイート', topic: 'benchmark', repo: 'my-benchmark', slug: 'benchmark-suite' },
  { label: 'Weekly report Automation', labelJa: '週次レポートAutomation', topic: 'automation', repo: 'my-weekly-report', slug: 'weekly-report-automation' },
  { label: 'Empty repository', labelJa: '空のリポジトリ', topic: 'model', repo: 'my-nyankoface-repo', slug: 'empty-repository' },
];

const typeConfig: Record<string, { title: string; titleJa: string; repoPlaceholder: string; cancelHref: string }> = {
  model: { title: 'Create a new model', titleJa: '新しいモデルを作成', repoPlaceholder: 'my-awesome-model', cancelHref: '/models' },
  dataset: { title: 'Create a new dataset', titleJa: '新しいデータセットを作成', repoPlaceholder: 'my-awesome-dataset', cancelHref: '/datasets' },
  space: { title: 'Create a new Space', titleJa: '新しいSpaceを作成', repoPlaceholder: 'my-awesome-space', cancelHref: '/spaces' },
  skill: { title: 'Create a new Skill', titleJa: '新しいスキルを作成', repoPlaceholder: 'my-agent-skill', cancelHref: '/skills' },
  mcp: { title: 'Create a new MCP server', titleJa: '新しいMCPサーバーを作成', repoPlaceholder: 'my-mcp-server', cancelHref: '/mcps' },
  prompt: { title: 'Create a new Prompt', titleJa: '新しいプロンプトを作成', repoPlaceholder: 'my-agent-prompt', cancelHref: '/prompts' },
  doc: { title: 'Create your knowledge publication', titleJa: 'ナレッジ出版を作成', repoPlaceholder: 'my-knowledge', cancelHref: '/docs' },
  character: { title: 'Create a new character repository', titleJa: '新しいキャラクターリポジトリを作成', repoPlaceholder: 'my-character-assets', cancelHref: '/characters' },
  benchmark: { title: 'Create a new benchmark', titleJa: '新しいベンチマークを作成', repoPlaceholder: 'my-evaluation-suite', cancelHref: '/benchmarks' },
  automation: { title: 'Create a new Automation', titleJa: '新しいAutomationを作成', repoPlaceholder: 'my-safe-automation', cancelHref: '/automations' },
};

export default async function NewRepoGuidePage({
  searchParams,
}: {
  searchParams?: Promise<{ type?: string; template?: string; format?: string }>;
}) {
  const resolvedSearchParams = await searchParams;
  if (resolvedSearchParams?.type === 'pages') {
    redirect('/pages/deploy');
  }
  const locale = await getLocale();
  const requestedType = resolvedSearchParams?.type === 'model' || resolvedSearchParams?.type === 'dataset' || resolvedSearchParams?.type === 'space' || resolvedSearchParams?.type === 'skill' || resolvedSearchParams?.type === 'mcp' || resolvedSearchParams?.type === 'prompt' || resolvedSearchParams?.type === 'doc' || resolvedSearchParams?.type === 'character' || resolvedSearchParams?.type === 'benchmark' || resolvedSearchParams?.type === 'automation'
    ? resolvedSearchParams.type
    : 'space';
  const config = typeConfig[requestedType];
  const rawTemplate = resolvedSearchParams?.template?.trim() || '';
  const selectedTemplate = templates.find((template) => template.slug === rawTemplate) || null;
  const duplicateSource = rawTemplate && rawTemplate.includes('/') ? rawTemplate : '';
  const effectiveType = selectedTemplate?.topic || requestedType;
  const effectiveConfig = typeConfig[effectiveType];
  const duplicateRepoName = duplicateSource ? `${duplicateSource.split('/').pop()}-copy` : '';
  const orderedTypes = [
    ...repoTypes.filter((type) => type.topic === effectiveType),
    ...repoTypes.filter((type) => type.topic !== effectiveType),
  ];
  const isDoc = effectiveType === 'doc';
  const knowledgeFormat = isDoc && (resolvedSearchParams?.template === 'thread-knowledge' || resolvedSearchParams?.format === 'thread')
    ? 'thread'
    : 'article';
  const isCharacter = effectiveType === 'character';

  return (
    <div className="mx-auto max-w-[1536px] py-5">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4 border-b border-zinc-100 pb-5">
        <div>
          <h1 className="text-3xl font-extrabold tracking-normal text-zinc-950">{ui(locale, effectiveConfig.titleJa, effectiveConfig.title)}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
            {isDoc
              ? ui(locale, '個人またはチーム用に一度だけ作成します。その後articles/*.mdを追加すると、公開MarkdownがDocsに集約されます。', 'Create this once for yourself or a team. Add articles/*.md afterward; NyankoFace collects every published Markdown entry into Docs.')
              : ui(locale, 'リポジトリ種別を選び、Forgejoで作成を完了します。選択したトピックに対応するNyankoFace一覧へ表示されます。', 'Choose the NyankoFace repository type first, then finish creation in Forgejo. The selected topic keeps the repository visible in its matching NyankoFace directory.')}
          </p>
          {duplicateSource ? (
            <p className="mt-2 inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-xs font-semibold text-zinc-600">
              <HfIcon name="fork" className="h-3 w-3" />
              {ui(locale, `${duplicateSource} を複製`, `Duplicating from ${duplicateSource}`)}
            </p>
          ) : null}
        </div>
        <button
          type="submit"
          form="nyankoface-new-repo-form"
          className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-950 px-4 text-sm font-semibold text-white hover:bg-zinc-800"
        >
          <HfIcon name="plus" className="h-3 w-3" />
          {ui(locale, 'Forgejoで作成', 'Open Forgejo create')}
        </button>
      </div>

      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-5 py-4">
            <h2 className="text-base font-bold text-zinc-950">{ui(locale, 'リポジトリ情報', 'Repository details')}</h2>
          </div>

          <form id="nyankoface-new-repo-form" action="/git/repo/create" method="get" className="space-y-6 p-5">
            {selectedTemplate ? <input type="hidden" name="template" value={selectedTemplate.slug} /> : null}
            {duplicateSource ? <input type="hidden" name="duplicate_from" value={duplicateSource} /> : null}
            <fieldset>
              <legend className="mb-2 text-sm font-semibold text-zinc-900">{ui(locale, 'リポジトリ種別', 'Repository type')}</legend>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {orderedTypes.map((type) => (
                  <label
                    key={type.topic}
                    className="flex cursor-pointer gap-3 rounded-lg border border-zinc-200 p-3 transition hover:border-zinc-300 hover:bg-zinc-50"
                  >
                    <input
                      type="radio"
                      name="topic"
                      value={type.topic}
                      defaultChecked={type.topic === effectiveType}
                      className="mt-1 h-4 w-4 accent-zinc-950"
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 text-sm font-bold text-zinc-950">
                        <HfIcon name={type.icon} className="h-3.5 w-3.5 text-zinc-400" />
                        {ui(locale, type.labelJa, type.label)}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-zinc-500">{ui(locale, type.descriptionJa, type.description)}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset hidden={!isDoc} data-knowledge-format-fieldset="true">
              <legend className="mb-2 text-sm font-semibold text-zinc-900">{ui(locale, 'ナレッジ形式', 'Knowledge format')}</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-200 p-3 hover:bg-zinc-50">
                  <input type="radio" name="knowledge_format" value="article" defaultChecked={knowledgeFormat === 'article'} disabled={!isDoc} className="mt-1 h-4 w-4 accent-zinc-950" />
                  <span>
                    <span className="block text-sm font-bold text-zinc-950">{ui(locale, '通常の記事／Wiki', 'Article / Wiki')}</span>
                    <span className="block text-xs leading-5 text-zinc-500">{ui(locale, 'これまでのMarkdown記事形式です。', 'The existing Markdown article format.')}</span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/50 p-3 hover:bg-amber-50">
                  <input type="radio" name="knowledge_format" value="thread" defaultChecked={knowledgeFormat === 'thread'} disabled={!isDoc} className="mt-1 h-4 w-4 accent-amber-700" />
                  <span>
                    <span className="block text-sm font-bold text-zinc-950">{ui(locale, 'スレッド解説', 'Thread explanation')}</span>
                    <span className="block text-xs leading-5 text-zinc-600">{ui(locale, '投稿番号・名前・返信参照を持つ形式です。', 'Posts with numbers, names, and reply references.')}</span>
                  </span>
                </label>
              </div>
              <details hidden={knowledgeFormat !== 'thread'} data-knowledge-format-help="true" className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-50">
                <summary className="cursor-pointer font-semibold">{ui(locale, 'スレッド形式の保存例', 'Thread format example')}</summary>
                <pre className="mt-3 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded bg-white/70 p-3 text-xs leading-5 dark:bg-zinc-950/40"><code>{`---
format: thread
title: スレッド解説サンプル
description: 投稿形式で仕組みを順番に説明します。
thread:
  part: Part.1
  theme: 仕組みを順番に解説
  rules: [短く具体的に書く]
posts:
  - number: 1
    name: 名無しさん
    body: |
      まず全体像を教えてください。
  - number: 2
    name: 解説役
    role: 回答
    body: |
      >>1 に答えます。入口から順に説明します。
---`}</code></pre>
              </details>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-[180px_minmax(0,1fr)]">
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-zinc-900">{ui(locale, '所有者', 'Owner')}</span>
                <select name="owner" className="h-10 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900">
                  <option>nyankoface</option>
                  <option>nyankoface-admin</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-zinc-900">{ui(locale, 'リポジトリ名', 'Repository name')}</span>
                <input
                  name="repo"
                  defaultValue={duplicateRepoName || selectedTemplate?.repo || ''}
                  placeholder={effectiveConfig.repoPlaceholder}
                  className="h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm text-zinc-900 placeholder:text-zinc-400"
                />
              </label>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-zinc-900">{ui(locale, '短い説明', 'Short description')}</span>
              <textarea
                name="description"
                rows={3}
                defaultValue={duplicateSource ? ui(locale, `${duplicateSource} の複製`, `Duplicate of ${duplicateSource}`) : ''}
                placeholder={ui(locale, '一覧とリポジトリ見出しに表示する簡潔な説明。', 'A concise description shown on listings and repository headers.')}
                className="w-full resize-none rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400"
              />
            </label>

            <fieldset>
              <legend className="mb-2 text-sm font-semibold text-zinc-900">{ui(locale, '公開範囲', 'Visibility')}</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-200 p-3 hover:bg-zinc-50">
                  <input type="radio" name="visibility" value="public" defaultChecked className="mt-1 h-4 w-4 accent-zinc-950" />
                  <span>
                    <span className="block text-sm font-bold text-zinc-950">{ui(locale, '公開', 'Public')}</span>
                    <span className="block text-xs leading-5 text-zinc-500">{ui(locale, '対応トピックを追加するとNyankoFaceの検索対象になります。', 'Appears in NyankoFace discovery after adding the matching topic.')}</span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-200 p-3 hover:bg-zinc-50">
                  <input type="radio" name="visibility" value="private" className="mt-1 h-4 w-4 accent-zinc-950" />
                  <span>
                    <span className="block text-sm font-bold text-zinc-950">{ui(locale, '非公開', 'Private')}</span>
                    <span className="block text-xs leading-5 text-zinc-500">{ui(locale, 'Forgejoの共同作業者だけが閲覧できます。', 'Visible only to collaborators in Forgejo.')}</span>
                  </span>
                </label>
              </div>
            </fieldset>

            <div className="flex flex-wrap items-center gap-3 border-t border-zinc-100 pt-5">
              <button
                type="submit"
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-950 px-4 text-sm font-semibold text-white hover:bg-zinc-800"
              >
                <HfIcon name="plus" className="h-3 w-3" />
                {ui(locale, 'Forgejoで続ける', 'Continue in Forgejo')}
              </button>
              <a href={effectiveConfig.cancelHref} className="text-sm font-medium text-zinc-500 hover:text-zinc-900">
                {ui(locale, 'キャンセル', 'Cancel')}
              </a>
            </div>
          </form>
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="mb-3 text-sm font-bold text-zinc-950">{ui(locale, 'スターターテンプレート', 'Starter templates')}</h2>
            <div className="space-y-2">
              {templates.map((template) => (
                <a
                  key={template.label}
                  href={`/new?type=${template.topic}&template=${encodeURIComponent(template.slug)}`}
                  className={
                    selectedTemplate?.slug === template.slug
                      ? 'grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 rounded-lg border border-zinc-900 bg-zinc-950 px-3 py-2 text-left text-sm font-semibold text-white'
                      : 'grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 rounded-lg border border-zinc-100 px-3 py-2 text-left text-sm text-zinc-700 hover:border-zinc-200 hover:bg-zinc-50'
                  }
                  aria-label={`${ui(locale, template.labelJa, template.label)} ${template.topic}`}
                >
                  <span className="min-w-0 truncate">
                    {ui(locale, template.labelJa, template.label)}
                  </span>
                  <span className={selectedTemplate?.slug === template.slug ? 'shrink-0 rounded bg-white/10 px-1.5 py-0.5 text-xs text-white' : 'shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500'}>
                    {template.topic}
                  </span>
                  <HfIcon name="arrowRight" className={selectedTemplate?.slug === template.slug ? 'h-3 w-3 text-white/70' : 'h-3 w-3 text-zinc-400'} />
                </a>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-bold text-zinc-950">{ui(locale, '必須トピック', 'Required topic')}</h2>
            {isDoc ? (
              <div className="space-y-3 text-sm leading-6 text-zinc-500">
                <p>{ui(locale, 'リポジトリに', 'Add ')} <code className="rounded bg-zinc-100 px-1.5 py-0.5">doc</code> {ui(locale, 'トピックを追加し、すべての記事を articles/*.md に保存します。', 'to the repository and store every publication in articles/*.md.')}</p>
                <div className="flex flex-wrap gap-1.5" aria-label="Doc topic example">
                  {['doc', 'knowledge', 'markdown'].map((topic) => <code key={topic} className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700">{topic}</code>)}
                </div>
                <p><strong className="text-zinc-700">{ui(locale, '記事タグ（複数可）:', 'Article tags (composable):')}</strong> news · how-to · reference · benchmark · research</p>
                <a href="/docs/nyankoface/docs-publishing-quickstart" className="inline-flex items-center gap-1.5 font-semibold text-teal-800 hover:underline">{ui(locale, '公開クイックスタートを読む', 'Read the publishing quickstart')} <HfIcon name="arrowRight" className="h-3 w-3" /></a>
              </div>
            ) : isCharacter ? (
              <div className="space-y-3 text-sm leading-6 text-zinc-500">
                <p>{ui(locale, 'リポジトリに', 'Add the ')} <code className="rounded bg-zinc-100 px-1.5 py-0.5">character</code> {ui(locale, 'トピックを追加し、対応形式もトピックで表します。NyankoFaceは実ファイルも検証します。', 'topic and describe supported formats with additional topics. NyankoFace also verifies the actual files.')}</p>
                <div className="flex flex-wrap gap-1.5" aria-label="Character topic examples">
                  {['purupuru', 'codex-pet', 'character-sheet', 'head-motion'].map((topic) => <code key={topic} className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700">{topic}</code>)}
                </div>
              </div>
            ) : (
              <p className="text-sm leading-6 text-zinc-500">
                {ui(locale, '作成後、NyankoFaceが索引できるようForgejoで', 'After creation, add the matching topic such as ')} <code className="rounded bg-zinc-100 px-1.5 py-0.5">prompt</code> {ui(locale, 'など対応トピックを追加します。プロンプトの版には', 'in Forgejo so NyankoFace can index it. Prompt versions use an additional topic such as ')} <code className="rounded bg-zinc-100 px-1.5 py-0.5">version-v8</code>{ui(locale, 'のような追加トピックを使います。', '.')}
              </p>
            )}
          </section>

          <section className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-bold text-zinc-950">{ui(locale, '推奨ファイル', 'Recommended files')}</h2>
            <ul className="space-y-2 text-sm text-zinc-500">
              <li className="flex items-center gap-2"><HfIcon name="file" className="h-3.5 w-3.5" />README.md</li>
              {isDoc ? (
                <>
                  <li className="flex items-center gap-2"><HfIcon name="folder" className="h-3.5 w-3.5" />{ui(locale, '各ナレッジ記事の articles/*.md', 'articles/*.md for every knowledge entry')}</li>
                  <li className="flex items-center gap-2"><HfIcon name="model" className="h-3.5 w-3.5" />{ui(locale, '共有記事素材の images/', 'images/ for shared article assets')}</li>
                </>
              ) : isCharacter ? (
                <>
                  {selectedTemplate?.slug === 'purupuru-pngtuber' ? (
                    <>
                      <li className="flex items-center gap-2"><HfIcon name="gear" className="h-3.5 w-3.5" />avatar/default-settings.json</li>
                      <li className="flex items-center gap-2"><HfIcon name="image" className="h-3.5 w-3.5" />{ui(locale, '正面6表情のeyes-*.png', 'Six frontal eyes-*.png states')}</li>
                      <li className="flex items-center gap-2"><HfIcon name="folder" className="h-3.5 w-3.5" />{ui(locale, '任意: avatar/directions/ と方向制御パッチ', 'Optional: avatar/directions/ and a direction-control patch')}</li>
                    </>
                  ) : selectedTemplate?.slug === 'character-sheets' ? (
                    <>
                      <li className="flex items-center gap-2"><HfIcon name="table" className="h-3.5 w-3.5" />metadata/characters.csv</li>
                      <li className="flex items-center gap-2"><HfIcon name="image" className="h-3.5 w-3.5" />assets/exports/</li>
                      <li className="flex items-center gap-2"><HfIcon name="image" className="h-3.5 w-3.5" />assets/thumbnails/</li>
                    </>
                  ) : (
                    <>
                      <li className="flex items-center gap-2"><HfIcon name="file" className="h-3.5 w-3.5" />pet.json</li>
                      <li className="flex items-center gap-2"><HfIcon name="image" className="h-3.5 w-3.5" />spritesheet.webp · 1536×1872</li>
                      <li className="flex items-center gap-2"><HfIcon name="table" className="h-3.5 w-3.5" />{ui(locale, '推奨: QA contact sheet と validation.json', 'Recommended: QA contact sheet and validation.json')}</li>
                    </>
                  )}
                </>
              ) : (
                <>
                  <li className="flex items-center gap-2"><HfIcon name="folder" className="h-3.5 w-3.5" />{ui(locale, 'Space用のapp.pyまたはDockerfile', 'app.py or Dockerfile for Spaces')}</li>
                  <li className="flex items-center gap-2"><HfIcon name="download" className="h-3.5 w-3.5" />{ui(locale, '大きな成果物にはGit LFS', 'Git LFS for large artifacts')}</li>
                </>
              )}
            </ul>
          </section>
        </aside>
      </div>
      <script
        dangerouslySetInnerHTML={{
          __html: `
(() => {
  const form = document.getElementById("nyankoface-new-repo-form");
  if (!form) return;
  const persistCreateState = () => {
    const params = new URLSearchParams();
    for (const el of Array.from(form.elements)) {
      if (!el.name || el.disabled) continue;
      if ((el.type === "radio" || el.type === "checkbox") && !el.checked) continue;
      if (el.value == null || el.value === "") continue;
      params.set(el.name, el.value);
    }
    if (!params.toString()) return;
    try {
      localStorage.setItem("nyankoface.pendingCreateUrl", "/git/repo/create?" + params.toString());
      localStorage.setItem("nyankoface.pendingCreateLabel", "Resume repository creation");
    } catch {}
    document.cookie = "nyankoface_pending_create=" + encodeURIComponent("/git/repo/create?" + params.toString()) + "; path=/; max-age=1800; SameSite=Lax";
  };
  persistCreateState();
  form.addEventListener("input", persistCreateState);
  form.addEventListener("change", persistCreateState);
  form.addEventListener("submit", persistCreateState);
  const formatFieldset = document.querySelector("[data-knowledge-format-fieldset]");
  const formatInputs = Array.from(form.querySelectorAll('input[name="knowledge_format"]'));
  const formatHelp = document.querySelector("[data-knowledge-format-help]");
  const syncKnowledgeFormatHelp = () => {
    if (!(formatHelp instanceof HTMLElement)) return;
    const selected = form.querySelector('input[name="knowledge_format"]:checked');
    formatHelp.hidden = selected?.value !== "thread";
  };
  const syncKnowledgeFormatFieldset = () => {
    const selectedTopic = form.querySelector('input[name="topic"]:checked');
    const docSelected = selectedTopic?.value === "doc";
    if (formatFieldset instanceof HTMLElement) formatFieldset.hidden = !docSelected;
    formatInputs.forEach((input) => { input.disabled = !docSelected; });
    syncKnowledgeFormatHelp();
  };
  formatInputs.forEach((input) => input.addEventListener("change", syncKnowledgeFormatHelp));
  form.querySelectorAll('input[name="topic"]').forEach((input) => input.addEventListener("change", syncKnowledgeFormatFieldset));
  syncKnowledgeFormatFieldset();
})();
          `,
        }}
      />
    </div>
  );
}
