import matter from 'gray-matter';
import { marked, Renderer } from 'marked';
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

marked.setOptions({
  gfm: true,
  breaks: false,
});

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

function sanitizeRenderedMarkdown(html: string): string {
  return sanitizeHtml(html, {
    allowedTags: [
      ...sanitizeHtml.defaults.allowedTags,
      'details', 'summary', 'figure', 'figcaption', 'button', 'img', 'input', 'picture', 'source', 'video',
    ],
    allowedAttributes: {
      ...sanitizeHtml.defaults.allowedAttributes,
      '*': ['class', 'id', 'title', 'align', 'data-language', 'data-language-known'],
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
  const rendered = marked.parse(markdown, { async: false, renderer: createMarkdownRenderer(urls?.locale) }) as string;
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
