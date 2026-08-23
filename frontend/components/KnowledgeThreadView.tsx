import MarkdownBody, { MarkdownBodyThemeProvider } from './MarkdownBody';
import { renderMarkdownBody, ReadmeRenderUrls } from '@/lib/markdown';
import { KnowledgeThread } from '@/lib/knowledge-thread';
import { Locale, ui } from '@/lib/i18n';

export default function KnowledgeThreadView({
  thread,
  introHtml,
  locale,
  renderUrls,
}: {
  thread: KnowledgeThread;
  introHtml: string;
  locale: Locale;
  renderUrls?: ReadmeRenderUrls;
}) {
  const postNumbers = new Set(thread.posts.map((post) => post.number));

  return (
    <MarkdownBodyThemeProvider>
      <section
      className="nyankoface-knowledge-thread min-w-0 max-w-full overflow-hidden"
      data-knowledge-format="thread"
      aria-label={ui(locale, 'スレッド解説', 'Thread explanation')}
    >
      {thread.metadata.part || thread.metadata.theme || thread.metadata.rules.length > 0 ? (
        <header className="mb-6 min-w-0 overflow-hidden rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-amber-950 dark:border-amber-800/70 dark:bg-amber-950/25 dark:text-amber-50 sm:p-5">
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-amber-700 dark:text-amber-300">
            <span>{ui(locale, 'スレッド情報', 'Thread details')}</span>
            {thread.metadata.part ? <span className="max-w-full truncate rounded-full bg-amber-200/70 px-2 py-1 normal-case tracking-normal dark:bg-amber-900/60">{thread.metadata.part}</span> : null}
          </div>
          {thread.metadata.theme ? <p className="mt-3 min-w-0 break-words text-sm font-semibold">{thread.metadata.theme}</p> : null}
          {thread.metadata.rules.length > 0 ? (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6 [overflow-wrap:anywhere]">
              {thread.metadata.rules.map((rule) => <li key={rule}>{rule}</li>)}
            </ul>
          ) : null}
        </header>
      ) : null}

      {introHtml ? (
        <MarkdownBody className="github-markdown-body prose-nyankoface mb-8 min-w-0 bg-transparent dark:bg-transparent" html={introHtml} />
      ) : null}

      {thread.posts.length > 0 ? (
        <div className="min-w-0 space-y-4" data-thread-posts>
          {thread.posts.map((post) => {
            const bodyHtml = renderMarkdownBody(post.bodyMarkdown, renderUrls || { locale });
            return (
              <article
                key={post.number}
                id={`thread-post-${post.number}`}
                className="min-w-0 max-w-full scroll-mt-6 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-900/70"
                data-thread-post-number={post.number}
              >
                <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-zinc-200 bg-zinc-50 px-4 py-3 text-sm dark:border-zinc-700 dark:bg-zinc-800/80 sm:px-5">
                  <span className="shrink-0 font-mono text-xs font-bold text-zinc-500 dark:text-zinc-400">#{post.number}</span>
                  <span className="min-w-0 max-w-full truncate font-bold text-zinc-950 dark:text-zinc-50" title={post.name}>{post.name}</span>
                  {post.role ? <span className="max-w-full truncate rounded-full bg-teal-100 px-2 py-0.5 text-[11px] font-semibold text-teal-800 dark:bg-teal-950/60 dark:text-teal-200" title={post.role}>{post.role}</span> : null}
                  {post.id ? <span className="max-w-full truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400" title={post.id}>ID:{post.id}</span> : null}
                  {post.postedAt ? <time className="ml-auto max-w-full truncate text-[11px] text-zinc-500 dark:text-zinc-400" dateTime={post.postedAt}>{post.postedAt}</time> : null}
                  {post.replyTo.length > 0 ? (
                    <div className="flex min-w-0 max-w-full flex-wrap items-center gap-1 text-[11px] text-zinc-500 dark:text-zinc-400" aria-label={ui(locale, '返信先', 'Replies to')}>
                      <span>{ui(locale, '返信', 'Reply')}</span>
                      {post.replyTo.map((target) => postNumbers.has(target) ? (
                        <a key={target} href={`#thread-post-${target}`} className="shrink-0 rounded-full bg-sky-100 px-2 py-0.5 font-mono font-semibold text-sky-800 hover:underline dark:bg-sky-950/60 dark:text-sky-200">#{target}</a>
                      ) : (
                        <span key={target} className="shrink-0 rounded-full bg-zinc-200 px-2 py-0.5 font-mono dark:bg-zinc-700">#{target}</span>
                      ))}
                    </div>
                  ) : null}
                </header>
                <div className="min-w-0 overflow-hidden px-4 py-4 sm:px-5">
                  {bodyHtml ? (
                    <MarkdownBody className="github-markdown-body prose-nyankoface min-w-0 max-w-full bg-transparent dark:bg-transparent" html={bodyHtml} />
                  ) : (
                    <p className="text-sm text-zinc-500 dark:text-zinc-400">{ui(locale, '本文はありません。', 'No post body.')}</p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-zinc-300 p-5 text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
          {ui(locale, 'スレッドの投稿はまだありません。通常の記事本文を表示しています。', 'This thread has no posts yet. The regular article body is shown instead.')}
        </p>
      )}

      {thread.metadata.sources.length > 0 ? (
        <footer className="mt-8 min-w-0 border-t border-zinc-200 pt-5 dark:border-zinc-700" data-thread-sources>
          <h2 className="text-xs font-bold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">{ui(locale, '参考資料', 'Sources')}</h2>
          <ul className="mt-3 min-w-0 space-y-2 text-sm">
            {thread.metadata.sources.map((source) => (
              <li key={`${source.label}-${source.url}`} className="min-w-0 max-w-full [overflow-wrap:anywhere]">
                <a href={source.url} rel="nofollow noreferrer" className="text-teal-800 hover:underline dark:text-teal-300">{source.label}</a>
              </li>
            ))}
          </ul>
        </footer>
      ) : null}
      </section>
    </MarkdownBodyThemeProvider>
  );
}
