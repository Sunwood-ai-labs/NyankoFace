import { getContents, getRepo, getTextFile, Repo, repoDefaultBranch, searchReposByTopicAndQuery, SortOption } from './forgejo';
import { parseReadme } from './markdown';
import { parseKnowledgeThread, KnowledgeThread } from './knowledge-thread';

export type KnowledgeArticleFormat = 'article' | 'thread';

export interface KnowledgeArticle {
  id: string;
  slug: string;
  title: string;
  description: string;
  topics: string[];
  owner: string;
  ownerAvatarUrl?: string;
  repository: string;
  repositoryId: number;
  branch: string;
  path: string;
  updatedAt: string;
  createdAt: string;
  emoji: string;
  format: KnowledgeArticleFormat;
  thread?: KnowledgeThread;
  readingMinutes: number;
  views: number;
  likes: number;
  metricsAvailable?: boolean;
  likesAvailable?: boolean;
  bodyHtml?: string;
  bodyMarkdown?: string;
}

export interface KnowledgeSearchResult {
  ok: boolean;
  data: KnowledgeArticle[];
  totalCount: number;
}

const articleDirectory = 'articles';
const KNOWLEDGE_CACHE_TTL_MS = Math.max(
  15,
  Number.parseInt(process.env.KNOWLEDGE_CACHE_TTL_SECONDS || '60', 10) || 60,
) * 1000;
const knowledgeCache = new Map<SortOption, { expiresAt: number; result: KnowledgeSearchResult }>();
const knowledgeLoads = new Map<SortOption, Promise<KnowledgeSearchResult>>();

function list(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean);
  if (typeof value === 'string') return value.split(',').map((item) => item.trim()).filter(Boolean);
  return [];
}

function firstHeading(markdown: string, fallback: string): string {
  return markdown.match(/^#\s+(.+)$/m)?.[1]?.trim() || fallback.replace(/-/g, ' ');
}

function firstParagraph(markdown: string): string {
  return markdown
    .replace(/^#.*$/gm, '')
    .split(/\n\s*\n/)
    .map((block) => block.replace(/[`*_>#\[\]]/g, '').replace(/\s+/g, ' ').trim())
    .find((block) => block.length > 30 && !block.startsWith('|')) || 'この記事を開いて、ナレッジの全文を確認してください。';
}

const topicEmoji: Array<{ topics: string[]; emoji: string }> = [
  { topics: ['news', 'release'], emoji: '📰' },
  { topics: ['recovery'], emoji: '🛟' },
  { topics: ['configuration'], emoji: '⚙️' },
  { topics: ['services'], emoji: '🏗️' },
  { topics: ['metrics'], emoji: '📊' },
  { topics: ['identity', 'permissions'], emoji: '🔐' },
  { topics: ['docs', 'publishing'], emoji: '📚' },
  { topics: ['catalog', 'topics', 'metadata'], emoji: '🗂️' },
  { topics: ['api'], emoji: '🔌' },
  { topics: ['routes'], emoji: '🗺️' },
  { topics: ['local-first'], emoji: '🏡' },
  { topics: ['community', 'design', 'accessibility'], emoji: '🧩' },
  { topics: ['cpu', 'inference'], emoji: '🧠' },
  { topics: ['visual-qa', 'themes'], emoji: '🔎' },
  { topics: ['agents', 'automation', 'review'], emoji: '🤖' },
  { topics: ['spaces', 'docker'], emoji: '🐳' },
  { topics: ['forgejo', 'git'], emoji: '🌿' },
];

const fallbackEmoji = ['✍️', '💡', '📝', '🔭', '🧪', '🪶'];

function publicationEmoji(slug: string, topics: string[]): string {
  const topicMatch = topicEmoji.find((candidate) => candidate.topics.some((topic) => topics.includes(topic)));
  if (topicMatch) return topicMatch.emoji;
  const hash = [...slug].reduce((total, character) => ((total * 31) + character.codePointAt(0)!) >>> 0, 0);
  return fallbackEmoji[hash % fallbackEmoji.length];
}

function readingMinutes(markdown: string): number {
  const words = markdown.trim().split(/\s+/).filter(Boolean).length;
  const japaneseCharacters = (markdown.match(/[\u3040-\u30ff\u3400-\u9fff]/g) || []).length;
  return Math.max(1, Math.ceil(Math.max(words / 220, japaneseCharacters / 500)));
}

async function loadPublication(repo: Repo): Promise<KnowledgeArticle[]> {
  const owner = repo.owner?.login || repo.full_name.split('/')[0];
  const branch = repoDefaultBranch(repo);
  const result = await getContents(owner, repo.name, articleDirectory, branch);
  const markdownFiles = result.ok && Array.isArray(result.data)
    ? result.data.filter((entry) => entry.type === 'file' && /\.md$/i.test(entry.name))
    : [];
  const loaded = await Promise.all(markdownFiles.map(async (entry) => {
    const raw = await getTextFile(owner, repo.name, entry.path, branch);
    if (!raw) return null;
    const parsed = parseReadme(raw);
    if (parsed.frontmatter.published === false) return null;
    const thread = parseKnowledgeThread(parsed.frontmatter);
    const slug = entry.name.replace(/\.md$/i, '');
    const title = typeof parsed.frontmatter.title === 'string'
      ? parsed.frontmatter.title.trim()
      : firstHeading(parsed.bodyMarkdown, slug);
    const description = typeof parsed.frontmatter.description === 'string'
      ? parsed.frontmatter.description.trim()
      : firstParagraph(parsed.bodyMarkdown);
    const topics = [...new Set([...list(parsed.frontmatter.topics), ...list(parsed.frontmatter.tags)])];
    return {
      id: `${owner}/${repo.name}/${slug}`,
      slug,
      title,
      description,
      topics,
      owner,
      ownerAvatarUrl: repo.owner?.avatar_url,
      repository: repo.name,
      repositoryId: repo.id,
      branch,
      path: entry.path,
      updatedAt: typeof parsed.frontmatter.updated === 'string' ? parsed.frontmatter.updated : repo.updated_at,
      createdAt: repo.created_at || repo.updated_at,
      emoji: typeof parsed.frontmatter.emoji === 'string' && parsed.frontmatter.emoji.trim()
        ? parsed.frontmatter.emoji.trim()
        : publicationEmoji(slug, topics),
      format: thread ? 'thread' : 'article',
      thread: thread || undefined,
      readingMinutes: readingMinutes([
        parsed.bodyMarkdown,
        ...(thread?.posts.map((post) => post.bodyMarkdown) || []),
      ].join('\n\n')),
      views: 0,
      likes: 0,
      bodyHtml: parsed.bodyHtml,
      bodyMarkdown: parsed.bodyMarkdown,
    } satisfies KnowledgeArticle;
  }));
  const unique = new Map<string, KnowledgeArticle>();
  for (const article of loaded.filter(Boolean) as KnowledgeArticle[]) {
    unique.set(article.slug, article);
  }
  return [...unique.values()];
}

export function matchesKnowledgeRepositoryIdentity(
  article: Pick<KnowledgeArticle, 'owner' | 'repository' | 'repositoryId'>,
  repo: Pick<Repo, 'id' | 'full_name'>,
): boolean {
  return repo.id === article.repositoryId
    && repo.full_name === `${article.owner}/${article.repository}`;
}

async function loadKnowledgeCatalog(sort: SortOption): Promise<KnowledgeSearchResult> {
  const cached = knowledgeCache.get(sort);
  if (cached && cached.expiresAt > Date.now()) {
    // Re-run the inexpensive public repository search on every request. The
    // expensive README parsing stays cached, while a public-to-private change
    // removes both article bodies and listing metadata immediately.
    const visibleRepositories = await searchReposByTopicAndQuery('doc', undefined, sort, 100);
    if (!visibleRepositories.ok) return { ok: false, data: [], totalCount: 0 };
    const visibleRepositoriesByName = new Map(
      visibleRepositories.data.map((repo) => [repo.full_name, repo]),
    );
    const visibleArticles = cached.result.data.filter((article) => {
      const repository = visibleRepositoriesByName.get(`${article.owner}/${article.repository}`);
      return repository ? matchesKnowledgeRepositoryIdentity(article, repository) : false;
    });
    return { ok: true, data: visibleArticles, totalCount: visibleArticles.length };
  }
  const running = knowledgeLoads.get(sort);
  if (running) return running;
  const load = (async () => {
    const publications = await searchReposByTopicAndQuery('doc', undefined, sort, 100);
    if (!publications.ok) return { ok: false, data: [], totalCount: 0 };
    const articles = (await Promise.all(publications.data.map(loadPublication))).flat();
    articles.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
    const result = { ok: true, data: articles, totalCount: articles.length };
    // Only public Forgejo content is admitted by searchRepos. No session or
    // permission-bearing response enters this process-wide cache.
    knowledgeCache.set(sort, { expiresAt: Date.now() + KNOWLEDGE_CACHE_TTL_MS, result });
    return result;
  })().finally(() => knowledgeLoads.delete(sort));
  knowledgeLoads.set(sort, load);
  return load;
}

export async function searchKnowledgeArticles(
  query?: string,
  sort: SortOption = 'updated',
): Promise<KnowledgeSearchResult> {
  const catalog = await loadKnowledgeCatalog(sort);
  if (!catalog.ok) return catalog;
  let articles = catalog.data;
  if (query) {
    const needle = query.toLocaleLowerCase();
    articles = articles.filter((article) => [article.title, article.description, article.owner, article.repository, ...article.topics]
      .some((value) => value.toLocaleLowerCase().includes(needle)));
  }
  return { ok: true, data: articles, totalCount: articles.length };
}

export async function getKnowledgeArticle(owner: string, slug: string): Promise<KnowledgeArticle | null> {
  const result = await searchKnowledgeArticles();
  const article = result.data.find((candidate) => candidate.owner === owner && candidate.slug === slug);
  if (!article) return null;
  // Catalog entries may be cached briefly, but body content must never outlive
  // the repository's public visibility. Forgejo is revalidated on every detail
  // request so a public-to-private transition fails closed immediately.
  const visibleRepository = await getRepo(article.owner, article.repository);
  return visibleRepository && matchesKnowledgeRepositoryIdentity(article, visibleRepository)
    ? article
    : null;
}
