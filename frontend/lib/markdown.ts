import matter from 'gray-matter';
import { Marked, Renderer } from 'marked';
import type { MarkedExtension, RendererThis, Token, Tokens, TokenizerThis } from 'marked';
import sanitizeHtml from 'sanitize-html';
import { highlightCode, normalizeCodeLanguage } from './syntax-highlight';

export interface ModelCardFrontmatter {
  license?: string;
  pipeline_tag?: string;
  language?: string | string[];
  tags?: string[];
  [key: string]: unknown;
}

export interface ParsedReadme {
  frontmatter: ModelCardFrontmatter;
  bodyHtml: string;
  bodyMarkdown: string;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

interface CodeFenceInfo {
  language: string;
  title?: string;
}

function parseCodeFenceInfo(infoString?: string): CodeFenceInfo {
  const info = infoString?.trim() || '';
  const language = normalizeCodeLanguage(info.match(/^([^\s{]+)/)?.[1]);
  const titleMatch = info.match(/(?:^|\s)(?:title|filename)=(?:"([^"]+)"|'([^']+)'|([^\s}]+))/i);
  return { language, title: titleMatch?.[1] || titleMatch?.[2] || titleMatch?.[3] };
}

function renderCodeBlock(source: string, infoString?: string, locale: 'ja' | 'en' = 'en'): string {
  const { language, title } = parseCodeFenceInfo(infoString);
  if (language === 'mermaid') {
    return `<pre><code class="language-mermaid">${escapeHtml(source)}</code></pre>`;
  }
  const highlighted = highlightCode(source, language);
  const displayLanguage = highlighted.knownLanguage ? language : 'text';
  const label = title || displayLanguage;
  const knownAttribute = highlighted.knownLanguage ? 'true' : 'false';
  const copyLabel = locale === 'ja' ? 'コピー' : 'Copy';
  const accessibleCopyLabel = locale === 'ja' ? `${displayLanguage}のコードをコピー` : `Copy ${displayLanguage} code`;
  return [
    `<figure class="nyankoface-code-block" data-language="${escapeHtml(displayLanguage)}" data-language-known="${knownAttribute}">`,
    '<figcaption class="nyankoface-code-header">',
    `<span class="nyankoface-code-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`,
    title ? `<span class="nyankoface-code-language">${escapeHtml(displayLanguage)}</span>` : '',
    `<button type="button" class="nyankoface-code-copy" data-nyankoface-copy-code aria-label="${escapeHtml(accessibleCopyLabel)}">${copyLabel}</button>`,
    '</figcaption>',
    `<pre tabindex="0" aria-label="${escapeHtml(label)} code"><code class="hljs language-${escapeHtml(displayLanguage)}">${highlighted.html}</code></pre>`,
    '<span class="nyankoface-code-copy-status" data-nyankoface-copy-status role="status" aria-live="polite"></span>',
    '</figure>',
  ].join('');
}

function createMarkdownRenderer(locale: 'ja' | 'en' = 'en'): Renderer {
  const renderer = new Renderer();
  renderer.code = (code: string, infoString: string | undefined): string => renderCodeBlock(code, infoString, locale);
  return renderer;
}

type GithubAlertType = 'NOTE' | 'TIP' | 'IMPORTANT' | 'WARNING' | 'CAUTION';
type NyankofaceBlockType = 'github-alert' | 'zenn-message' | 'zenn-details';

interface NyankofaceBlockToken extends Tokens.Generic {
  type: 'nyankoface-block';
  blockType: NyankofaceBlockType;
  tokens: Token[];
  alertType?: GithubAlertType;
  messageVariant?: 'default' | 'alert';
  title?: string;
}

const GITHUB_ALERT_PRESENTATION: Record<GithubAlertType, {
  icon: string;
  labelEn: string;
  labelJa: string;
  className: string;
}> = {
  NOTE: {
    icon: 'ⓘ',
    labelEn: 'Note',
    labelJa: '補足',
    className: 'border-sky-200 border-l-sky-500 bg-sky-50 text-sky-950 dark:border-sky-800 dark:border-l-sky-400 dark:bg-sky-950/30 dark:text-sky-100',
  },
  TIP: {
    icon: '✦',
    labelEn: 'Tip',
    labelJa: 'ヒント',
    className: 'border-emerald-200 border-l-emerald-500 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:border-l-emerald-400 dark:bg-emerald-950/30 dark:text-emerald-100',
  },
  IMPORTANT: {
    icon: '◆',
    labelEn: 'Important',
    labelJa: '重要',
    className: 'border-violet-200 border-l-violet-500 bg-violet-50 text-violet-950 dark:border-violet-800 dark:border-l-violet-400 dark:bg-violet-950/30 dark:text-violet-100',
  },
  WARNING: {
    icon: '⚠',
    labelEn: 'Warning',
    labelJa: '警告',
    className: 'border-amber-200 border-l-amber-500 bg-amber-50 text-amber-950 dark:border-amber-800 dark:border-l-amber-400 dark:bg-amber-950/30 dark:text-amber-100',
  },
  CAUTION: {
    icon: '⛔',
    labelEn: 'Caution',
    labelJa: '注意',
    className: 'border-rose-200 border-l-rose-500 bg-rose-50 text-rose-950 dark:border-rose-800 dark:border-l-rose-400 dark:bg-rose-950/30 dark:text-rose-100',
  },
};

const ZENN_MESSAGE_PRESENTATION = {
  default: {
    icon: '💬',
    labelEn: 'Message',
    labelJa: 'メッセージ',
    className: 'border-cyan-200 border-l-cyan-500 bg-cyan-50 text-cyan-950 dark:border-cyan-800 dark:border-l-cyan-400 dark:bg-cyan-950/30 dark:text-cyan-100',
  },
  alert: {
    icon: '⚠',
    labelEn: 'Alert',
    labelJa: '警告',
    className: 'border-orange-200 border-l-orange-500 bg-orange-50 text-orange-950 dark:border-orange-800 dark:border-l-orange-400 dark:bg-orange-950/30 dark:text-orange-100',
  },
} as const;

function parseZennOpeningLine(line: string): {
  blockType: 'zenn-message' | 'zenn-details';
  messageVariant?: 'default' | 'alert';
  title?: string;
} | null {
  const match = line.match(/^[ \t]{0,3}:::(message(?:[ \t]+alert)?|details(?:[ \t]+([^\r\n]*))?)[ \t]*$/i);
  if (!match) return null;
  const directive = match[1].toLowerCase();
  if (directive === 'message' || directive === 'message alert') {
    return {
      blockType: 'zenn-message',
      messageVariant: directive === 'message alert' ? 'alert' : 'default',
    };
  }
  return {
    blockType: 'zenn-details',
    title: match[2]?.trim() || undefined,
  };
}

function findZennClosingLine(source: string): { start: number; end: number } | null {
  let offset = 0;
  let nestedBlocks = 0;
  let fenceChar: '`' | '~' | null = null;
  let fenceLength = 0;

  while (offset < source.length) {
    const newlineIndex = source.indexOf('\n', offset);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(offset, end).replace(/\r?\n$/, '');
    const fence = line.match(/^[ \t]{0,3}(`{3,}|~{3,})/);

    if (fenceChar) {
      const closesFence = Boolean(
        fence
        && fence[1][0] === fenceChar
        && fence[1].length >= fenceLength
        && line.slice(fence[0].length).trim() === '',
      );
      if (closesFence) {
        fenceChar = null;
        fenceLength = 0;
      }
    } else if (fence) {
      fenceChar = fence[1][0] as '`' | '~';
      fenceLength = fence[1].length;
    } else if (parseZennOpeningLine(line)) {
      nestedBlocks += 1;
    } else if (/^[ \t]{0,3}:::[ \t]*$/.test(line)) {
      if (nestedBlocks > 0) {
        nestedBlocks -= 1;
      } else {
        return { start: offset, end };
      }
    }
    offset = end;
  }
  return null;
}

function blockTokens(lexer: TokenizerThis['lexer'], source: string): Token[] {
  const previousTop = lexer.state.top;
  lexer.state.top = true;
  try {
    return lexer.blockTokens(source);
  } finally {
    lexer.state.top = previousTop;
  }
}

function tokenizeGithubAlert(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
  const header = source.match(/^[ \t]{0,3}>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\r?\n|$)/i);
  if (!header) return undefined;

  let rawLength = header[0].length;
  const continuation = source.slice(rawLength).match(/^(?:[ \t]{0,3}>[^\r\n]*(?:\r?\n|$))+/);
  if (continuation) rawLength += continuation[0].length;
  const raw = source.slice(0, rawLength);
  const bodyMarkdown = raw
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.replace(/^[ \t]{0,3}>[ \t]?/, ''))
    .join('\n')
    .replace(/\n$/, '');

  return {
    type: 'nyankoface-block',
    blockType: 'github-alert',
    alertType: header[1].toUpperCase() as GithubAlertType,
    raw,
    tokens: blockTokens(this.lexer, bodyMarkdown),
  };
}

function tokenizeZennBlock(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
  const firstLineEnd = source.search(/\r?\n/);
  const firstLine = firstLineEnd === -1 ? source : source.slice(0, firstLineEnd);
  const opening = parseZennOpeningLine(firstLine);
  if (!opening || firstLineEnd === -1) return undefined;

  const openingLength = firstLineEnd + (source[firstLineEnd] === '\r' ? 2 : 1);
  const closing = findZennClosingLine(source.slice(openingLength));
  if (!closing) return undefined;

  const bodyMarkdown = source
    .slice(openingLength, openingLength + closing.start)
    .replace(/\r?\n$/, '');
  const raw = source.slice(0, openingLength + closing.end);
  return {
    type: 'nyankoface-block',
    ...opening,
    raw,
    tokens: blockTokens(this.lexer, bodyMarkdown),
  };
}

function startMarkdownBlock(source: string): number | undefined {
  const starts = [
    source.search(/(?:^|\n)(?=[ \t]{0,3}>[ \t]*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])/i),
    source.search(/(?:^|\n)(?=[ \t]{0,3}:::(?:message(?:[ \t]+alert)?|details(?:[ \t]+[^\r\n]*)?)[ \t]*(?:\r?\n|$))/i),
  ].filter((index) => index >= 0);
  if (starts.length === 0) return undefined;
  const start = Math.min(...starts);
  return source[start] === '\n' ? start + 1 : start;
}

function renderNyankofaceBlock(this: RendererThis, token: Tokens.Generic, locale: 'ja' | 'en'): string {
  const block = token as NyankofaceBlockToken;
  const body = this.parser.parse(block.tokens);

  if (block.blockType === 'zenn-details') {
    const title = escapeHtml(block.title || (locale === 'ja' ? '詳細' : 'Details'));
    return `<details class="my-5 overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/50"><summary class="cursor-pointer px-4 py-3 font-semibold text-zinc-800 dark:text-zinc-100">${title}</summary><div class="border-t border-zinc-200 p-4 dark:border-zinc-700">${body}</div></details>`;
  }

  const presentation = block.blockType === 'github-alert'
    ? GITHUB_ALERT_PRESENTATION[block.alertType || 'NOTE']
    : ZENN_MESSAGE_PRESENTATION[block.messageVariant || 'default'];
  const label = locale === 'ja' ? presentation.labelJa : presentation.labelEn;
  const dataType = block.blockType === 'github-alert' ? ` data-alert-type="${block.alertType}"` : '';
  const dataVariant = block.blockType === 'zenn-message' ? ` data-message-variant="${block.messageVariant || 'default'}"` : '';
  return `<aside class="my-5 rounded-lg border border-l-4 ${presentation.className} p-4" data-markdown-block="${block.blockType}"${dataType}${dataVariant} role="note"><div class="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wide"><span aria-hidden="true">${presentation.icon}</span><span>${label}</span></div><div>${body}</div></aside>`;
}

function createMarkdownExtensions(locale: 'ja' | 'en'): MarkedExtension {
  return {
    extensions: [{
      name: 'nyankoface-block',
      level: 'block',
      start: startMarkdownBlock,
      tokenizer(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
        return tokenizeGithubAlert.call(this, source) || tokenizeZennBlock.call(this, source);
      },
      renderer(this: RendererThis, token: Tokens.Generic): string {
        return renderNyankofaceBlock.call(this, token, locale);
      },
      childTokens: ['tokens'],
    }],
  };
}

function sanitizeRenderedMarkdown(html: string): string {
  return sanitizeHtml(html, {
    allowedTags: [
      ...sanitizeHtml.defaults.allowedTags,
      'aside', 'details', 'summary', 'figure', 'figcaption', 'button', 'img', 'input', 'picture', 'source', 'video',
    ],
    allowedAttributes: {
      ...sanitizeHtml.defaults.allowedAttributes,
      '*': ['class', 'id', 'title', 'align', 'data-language', 'data-language-known', 'data-markdown-block', 'data-alert-type', 'data-message-variant', 'role', 'aria-hidden'],
      a: ['href', 'name', 'target', 'rel', 'title'],
      button: ['type', 'class', 'data-nyankoface-copy-code', 'aria-label'],
      code: ['class'],
      img: ['src', 'srcset', 'alt', 'title', 'width', 'height', 'loading'],
      input: ['type', 'checked', 'disabled'],
      pre: ['class', 'tabindex', 'aria-label'],
      source: ['src', 'srcset', 'type', 'media'],
      span: ['class', 'title', 'data-nyankoface-copy-status', 'role', 'aria-live'],
      video: ['src', 'poster', 'controls', 'muted', 'loop', 'autoplay', 'playsinline', 'width', 'height'],
    },
    allowedSchemes: ['http', 'https', 'mailto'],
    allowProtocolRelative: false,
    enforceHtmlBoundary: true,
    transformTags: {
      a: sanitizeHtml.simpleTransform('a', { rel: 'nofollow noreferrer' }, true),
    },
  });
}

function renderMarkdown(markdown: string, urls?: ReadmeRenderUrls): string {
  const locale = urls?.locale || 'en';
  const parser = new Marked({
    gfm: true,
    breaks: false,
    ...createMarkdownExtensions(locale),
  });
  const rendered = parser.parse(markdown, { async: false, renderer: createMarkdownRenderer(locale) }) as string;
  return sanitizeRenderedMarkdown(resolveRelativeRepositoryUrls(rendered, urls));
}

export interface ReadmeRenderUrls {
  assetBaseUrl?: string;
  relativeLinkBaseUrl?: string;
  locale?: 'ja' | 'en';
}

function isAbsoluteOrAnchor(url: string): boolean {
  return /^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(url);
}

function resolveRelativeUrl(source: string, baseUrl: string): string {
  if (isAbsoluteOrAnchor(source)) return source;
  try {
    const resolved = new URL(source, `https://nyankoface.invalid${baseUrl}`);
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return source;
  }
}

function resolveRelativeRepositoryUrls(html: string, urls?: ReadmeRenderUrls): string {
  if (!urls) return html;
  let resolved = html;
  if (urls.assetBaseUrl) {
    const assetBaseUrl = urls.assetBaseUrl;
    resolved = resolved.replace(/(<img\b[^>]*?\bsrc=["'])([^"']+)(["'])/gi, (match, prefix, source, suffix) => {
      if (isAbsoluteOrAnchor(source)) return match;
      return `${prefix}${resolveRelativeUrl(source, assetBaseUrl)}${suffix}`;
    });
  }
  if (urls.relativeLinkBaseUrl) {
    const relativeLinkBaseUrl = urls.relativeLinkBaseUrl;
    resolved = resolved.replace(/(<a\b[^>]*?\bhref=["'])([^"']+)(["'])/gi, (match, prefix, href, suffix) => {
      if (isAbsoluteOrAnchor(href)) return match;
      return `${prefix}${resolveRelativeUrl(href, relativeLinkBaseUrl)}${suffix}`;
    });
  }
  return resolved;
}

export function parseReadme(raw: string | null, urls?: ReadmeRenderUrls): ParsedReadme {
  if (!raw) {
    return { frontmatter: {}, bodyHtml: '', bodyMarkdown: '' };
  }
  try {
    const { data, content } = matter(raw);
    const bodyHtml = renderMarkdown(content, urls);
    return { frontmatter: data || {}, bodyHtml, bodyMarkdown: content };
  } catch {
    const bodyHtml = renderMarkdown(raw, urls);
    return { frontmatter: {}, bodyHtml, bodyMarkdown: raw };
  }
}

export function languageList(language: string | string[] | undefined): string[] {
  if (!language) return [];
  if (Array.isArray(language)) return language;
  return [language];
}
