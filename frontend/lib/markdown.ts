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
  const match = line.match(/^ {0,3}:::(message(?:[ \t]+alert)?|details(?:[ \t]+([^\r\n]*))?)[ \t]*$/i);
  if (!match) return null;
  const directive = match[1].toLowerCase().replace(/\s+/g, ' ').trim();
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

type ZennFenceContainer =
  | { kind: 'blockquote' }
  | { kind: 'list'; contentIndent: number };

type ZennFenceMatch = {
  token: string;
  end: number;
  container?: ZennFenceContainer;
};

const LIST_CONTAINER_PREFIX = /^[ \t]{0,3}(?:[*+-]|\d+[.)])[ \t]{1,4}(?=\S)/;

const RAW_HTML_BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'base', 'blockquote', 'body', 'caption', 'center', 'col', 'colgroup',
  'dd', 'details', 'dialog', 'dir', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
  'form', 'frame', 'frameset', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hr', 'html',
  'iframe', 'legend', 'li', 'link', 'main', 'menu', 'menuitem', 'nav', 'ol', 'optgroup', 'option',
  'p', 'param', 'pre', 'script', 'section', 'summary', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead',
  'textarea', 'title', 'tr', 'track', 'ul', 'style',
]);
const RAW_HTML_TAGS_WITH_EXPLICIT_END = new Set(['pre', 'script', 'style', 'textarea']);

type RawHtmlBlockBoundary =
  | { kind: 'blank'; interruptsParagraph: boolean }
  | { kind: 'closing'; pattern: RegExp; interruptsParagraph: boolean };

type RawHtmlBlockState = {
  boundary: RawHtmlBlockBoundary;
  listContentIndent?: number;
};

type ZennBoundary = { start: number; end: number };

type ZennBoundaryIndex = {
  source: string;
  sourceLength: number;
  boundaries: Map<number, ZennBoundary>;
};

type ZennBoundaryContext = {
  boundaryIndex: ZennBoundaryIndex;
  sourceStart: number;
  sourceLength: number;
};

// Marked lexes block bodies by calling the same lexer with a new source string.
// Keep a short-lived context stack per lexer so nested bodies reuse the one
// root boundary index with adjusted source offsets instead of rescanning the
// remaining README for every recursive block.
const zennBoundaryStacks = new WeakMap<object, ZennBoundaryContext[]>();

function leadingIndentColumns(line: string): number {
  let columns = 0;
  for (const character of line) {
    if (character === ' ') {
      columns += 1;
    } else if (character === '\t') {
      columns += 4 - (columns % 4);
    } else {
      break;
    }
  }
  return columns;
}

function textColumns(text: string): number {
  let columns = 0;
  for (const character of text) {
    if (character === '\t') {
      columns += 4 - (columns % 4);
    } else {
      columns += 1;
    }
  }
  return columns;
}

function expandLeadingTabs(line: string): string {
  let columns = 0;
  let index = 0;
  let expanded = '';
  while (index < line.length) {
    const character = line[index];
    if (character === ' ') {
      expanded += character;
      columns += 1;
    } else if (character === '\t') {
      const width = 4 - (columns % 4);
      expanded += ' '.repeat(width);
      columns += width;
    } else {
      break;
    }
    index += 1;
  }
  return expanded + line.slice(index);
}

function matchZennFence(line: string): ZennFenceMatch | null {
  const blockquote = line.match(/^ {0,3}>[ \t]?(`{3,}|~{3,})/);
  if (blockquote) {
    return { token: blockquote[1], end: blockquote[0].length, container: { kind: 'blockquote' } };
  }
  const list = line.match(/^ {0,3}(?:[*+-]|\d+[.)])[ \t]{1,4}(?=\S)(`{3,}|~{3,})/);
  if (list) {
    return {
      token: list[1],
      end: list[0].length,
      container: {
        kind: 'list',
        contentIndent: textColumns(list[0].slice(0, -list[1].length)),
      },
    };
  }
  const plain = line.match(/^ {0,3}(`{3,}|~{3,})/);
  return plain ? { token: plain[1], end: plain[0].length } : null;
}

function stripZennContainerPrefix(line: string): string {
  const prefix = line.match(LIST_CONTAINER_PREFIX);
  return prefix ? line.slice(prefix[0].length) : line;
}

function isZennClosingLine(line: string, listContentIndent?: number): boolean {
  if (/^ {0,3}:::[ \t]*$/.test(line)) return true;
  if (listContentIndent === undefined) return false;
  const prefix = line.slice(0, listContentIndent);
  return /^[ \t]+$/.test(prefix) && /^:::[ \t]*$/.test(line.slice(listContentIndent));
}

function continuesZennFenceContainer(line: string, container: ZennFenceContainer): boolean {
  if (!line.trim()) return true;
  if (container.kind === 'blockquote') return /^ {0,3}>[ \t]?/.test(line);
  return leadingIndentColumns(line) >= container.contentIndent;
}

function gfmTableCells(line: string | undefined): string[] | undefined {
  if (line === undefined) return undefined;
  const trimmed = line.trim();
  if (!trimmed.includes('|')) return undefined;
  const content = trimmed.replace(/^\|/, '').replace(/\|$/, '');
  const cells: string[] = [];
  let cellStart = 0;
  let codeSpanLength = 0;
  for (let index = 0; index < content.length; index += 1) {
    const character = content[index];
    if (!codeSpanLength && character === '\\') {
      index += 1;
      continue;
    }
    if (character === '`') {
      let runLength = 1;
      while (content[index + runLength] === '`') runLength += 1;
      if (!codeSpanLength) codeSpanLength = runLength;
      else if (codeSpanLength === runLength) codeSpanLength = 0;
      index += runLength - 1;
      continue;
    }
    if (character === '|' && !codeSpanLength) {
      cells.push(content.slice(cellStart, index));
      cellStart = index + 1;
    }
  }
  cells.push(content.slice(cellStart));
  return cells;
}

function isGfmTableDelimiter(line: string, headerLine?: string): boolean {
  const cells = gfmTableCells(line);
  const headerCells = gfmTableCells(headerLine);
  return Boolean(
    cells
    && headerCells
    && cells.length === headerCells.length
    && cells.every((cell) => /^:?-+:?$/.test(cell.trim())),
  );
}

function startsMarkdownBlock(line: string, paragraphActive = false, previousLine?: string): boolean {
  if (leadingIndentColumns(line) >= 4) return !paragraphActive;
  const content = line.replace(/^ {0,3}/, '');
  const orderedList = content.match(/^(\d{1,9})[.)][ \t]+/);
  if (orderedList) return !paragraphActive || Number.parseInt(orderedList[1], 10) === 1;
  const shortSetextUnderline = /^(?:-[ \t]*){1,2}$/.test(content);
  return isGfmTableDelimiter(content, previousLine)
    || (shortSetextUnderline && paragraphActive)
    || /^(?:#{1,6}(?:[ \t]+|$)|={1,}[ \t]*$|(?:-[ \t]*){3,}$|(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$|[*+-][ \t]+|>[ \t]?)/.test(content);
}

function sameZennFenceContainer(left: ZennFenceContainer | undefined, right: ZennFenceContainer | undefined): boolean {
  if (!left || !right) return left === right;
  if (left.kind !== right.kind) return false;
  if (left.kind === 'blockquote' || right.kind === 'blockquote') return true;
  return left.contentIndent === right.contentIndent;
}

function matchRawHtmlOpening(line: string): { tagName: string; raw: string } | undefined {
  const tag = line.match(/^<([A-Za-z][A-Za-z0-9-]*)/);
  if (!tag) return undefined;
  let index = tag[0].length;
  while (index < line.length) {
    while (/[ \t]/.test(line[index] || '')) index += 1;
    if (line[index] === '>') return { tagName: tag[1], raw: line.slice(0, index + 1) };
    if (line[index] === '/') {
      let closingIndex = index + 1;
      while (/[ \t]/.test(line[closingIndex] || '')) closingIndex += 1;
      if (line[closingIndex] === '>') {
        return { tagName: tag[1], raw: line.slice(0, closingIndex + 1) };
      }
      return undefined;
    }
    const attribute = line.slice(index).match(/^[A-Za-z_:][A-Za-z0-9_.:-]*/);
    if (!attribute) return undefined;
    index += attribute[0].length;
    while (/[ \t]/.test(line[index] || '')) index += 1;
    if (line[index] !== '=') continue;
    index += 1;
    while (/[ \t]/.test(line[index] || '')) index += 1;
    const quote = line[index] === '"' || line[index] === "'" ? line[index] : undefined;
    if (quote) {
      index += 1;
      while (index < line.length && line[index] !== quote) index += 1;
      if (line[index] !== quote) return undefined;
      index += 1;
      continue;
    }
    const value = line.slice(index).match(/^[^\s"'=<>`]+/);
    if (!value) return undefined;
    index += value[0].length;
  }
  return undefined;
}

function rawHtmlBlockEnd(line: string): RawHtmlBlockBoundary | null {
  const trimmed = line.replace(/^[ \t]{0,3}/, '');
  if (trimmed.startsWith('<!--')) return trimmed.includes('-->') ? null : { kind: 'closing', pattern: /-->/, interruptsParagraph: true };
  if (trimmed.startsWith('<?')) return trimmed.includes('?>') ? null : { kind: 'closing', pattern: /\?>/, interruptsParagraph: true };
  if (/^<!\[CDATA\[/.test(trimmed)) return trimmed.includes(']]>') ? null : { kind: 'closing', pattern: /\]\]>/, interruptsParagraph: true };
  if (/^<![A-Z]/.test(trimmed)) return trimmed.includes('>') ? null : { kind: 'closing', pattern: />/, interruptsParagraph: true };
  const closingTag = trimmed.match(/^<\/([A-Za-z][A-Za-z0-9-]*)>/);
  if (closingTag) {
    return {
      kind: 'blank',
      interruptsParagraph: RAW_HTML_BLOCK_TAGS.has(closingTag[1].toLowerCase()),
    };
  }
  const opening = matchRawHtmlOpening(trimmed);
  if (!opening) {
    const partialExplicitOpening = trimmed.match(/^<([A-Za-z][A-Za-z0-9-]*)(?=\s|$)/);
    if (partialExplicitOpening && RAW_HTML_TAGS_WITH_EXPLICIT_END.has(partialExplicitOpening[1].toLowerCase())) {
      const tagName = partialExplicitOpening[1].toLowerCase();
      return { kind: 'closing', pattern: new RegExp(`</${tagName}\\s*>`, 'i'), interruptsParagraph: true };
    }
    if (partialExplicitOpening && RAW_HTML_BLOCK_TAGS.has(partialExplicitOpening[1].toLowerCase())) {
      return { kind: 'blank', interruptsParagraph: true };
    }
    return null;
  }
  const tagName = opening.tagName.toLowerCase();
  const isBlockTag = RAW_HTML_BLOCK_TAGS.has(tagName);
  const isSelfClosing = /\/\s*>$/.test(opening.raw);
  if (isSelfClosing) {
    if (!isBlockTag && trimmed.slice(opening.raw.length).trim() !== '') return null;
    return { kind: 'blank', interruptsParagraph: isBlockTag };
  }
  const closing = new RegExp(`</${tagName}>`, 'i');
  if (RAW_HTML_TAGS_WITH_EXPLICIT_END.has(tagName)) {
    return closing.test(trimmed.slice(opening.raw.length))
      ? null
      : { kind: 'closing', pattern: closing, interruptsParagraph: true };
  }
  if (!isBlockTag && trimmed.slice(opening.raw.length).trim() !== '') return null;
  return { kind: 'blank', interruptsParagraph: isBlockTag };
}

function buildZennBoundaryIndex(source: string): ZennBoundaryIndex {
  const boundaries = new Map<number, ZennBoundary>();
  const openings: Array<{ offset: number; listContentIndent?: number }> = [];
  let offset = 0;
  let fenceChar: '`' | '~' | null = null;
  let fenceLength = 0;
  let fenceContainer: ZennFenceContainer | undefined;
  let htmlBlockEnd: RawHtmlBlockState | null = null;
  let paragraphActive = false;
  let previousLine: string | undefined;

  while (offset < source.length) {
    const newlineIndex = source.indexOf('\n', offset);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(offset, end).replace(/\r?\n$/, '');

    if (!fenceChar) {
      if (htmlBlockEnd) {
        const indentation = line.match(/^[ \t]*/)?.[0].length || 0;
        const endsListContainer = htmlBlockEnd.listContentIndent !== undefined
          && line.trim() !== ''
          && indentation < htmlBlockEnd.listContentIndent;
        if (endsListContainer) {
          htmlBlockEnd = null;
          paragraphActive = false;
        } else {
          const endsAtBoundary = htmlBlockEnd.boundary.kind === 'blank'
            ? line.trim() === ''
            : htmlBlockEnd.boundary.pattern.test(line);
          if (endsAtBoundary) {
            htmlBlockEnd = null;
            paragraphActive = false;
          }
          previousLine = line;
          offset = end;
          continue;
        }
      }
      const rawHtml = rawHtmlBlockEnd(stripZennContainerPrefix(line));
      if (rawHtml && (!paragraphActive || rawHtml.interruptsParagraph)) {
        const listPrefix = line.match(LIST_CONTAINER_PREFIX);
        htmlBlockEnd = {
          boundary: rawHtml,
          listContentIndent: listPrefix?.[0].length,
        };
        paragraphActive = false;
        previousLine = line;
        offset = end;
        continue;
      }
      if (!rawHtml && /^\s*(?:<!--|<\?|<![A-Z])/.test(line)) {
        paragraphActive = false;
        previousLine = line;
        offset = end;
        continue;
      }
    }

    const fence = matchZennFence(line);

    if (fenceChar && fenceContainer && !continuesZennFenceContainer(line, fenceContainer)) {
      fenceChar = null;
      fenceLength = 0;
      fenceContainer = undefined;
    }

    if (fenceChar) {
      const closesFence = Boolean(
        fence
        && fence.token[0] === fenceChar
        && fence.token.length >= fenceLength
        && sameZennFenceContainer(fence.container, fenceContainer)
        && line.slice(fence.end).trim() === '',
      );
      if (closesFence) {
        fenceChar = null;
        fenceLength = 0;
        fenceContainer = undefined;
        paragraphActive = false;
      }
    } else if (fence) {
      const suffix = line.slice(fence.end);
      if (fence.token[0] !== '`' || !suffix.includes('`')) {
        fenceChar = fence.token[0] as '`' | '~';
        fenceLength = fence.token.length;
        fenceContainer = fence.container;
        paragraphActive = false;
      }
    } else if (parseZennOpeningLine(stripZennContainerPrefix(line))) {
      const listPrefix = line.match(LIST_CONTAINER_PREFIX);
      openings.push({ offset, listContentIndent: listPrefix?.[0].length });
      paragraphActive = false;
    } else if (isZennClosingLine(line, openings.at(-1)?.listContentIndent)) {
      while (
        openings.at(-1)?.listContentIndent !== undefined
        && line.trim() !== ''
        && leadingIndentColumns(line) < (openings.at(-1)?.listContentIndent || 0)
      ) {
        openings.pop();
      }
      if (openings.length === 0) {
        previousLine = line;
        offset = end;
        continue;
      }
      const opening = openings.pop();
      if (opening !== undefined) {
        boundaries.set(opening.offset, { start: offset, end });
      }
      paragraphActive = false;
    } else if (line.trim() === '') {
      paragraphActive = false;
    } else {
      paragraphActive = !startsMarkdownBlock(line, paragraphActive, previousLine);
    }
    previousLine = line;
    offset = end;
  }
  return { source, sourceLength: source.length, boundaries };
}

function blockTokens(
  lexer: TokenizerThis['lexer'],
  source: string,
  boundaryIndex = buildZennBoundaryIndex(source),
  sourceStart = 0,
): Token[] {
  const stack = zennBoundaryStacks.get(lexer) || [];
  stack.push({ boundaryIndex, sourceStart, sourceLength: source.length });
  zennBoundaryStacks.set(lexer, stack);
  const previousTop = lexer.state.top;
  lexer.state.top = true;
  try {
    return lexer.blockTokens(source);
  } finally {
    lexer.state.top = previousTop;
    stack.pop();
    if (stack.length === 0) zennBoundaryStacks.delete(lexer);
  }
}

function tokenizeGithubAlert(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
  const header = source.match(/^ {0,3}>[ \t]?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\r?\n|$)/i);
  if (!header) return undefined;

  let rawLength = header[0].length;
  let cursor = rawLength;
  let paragraphActive = false;
  while (cursor < source.length) {
    const newlineIndex = source.indexOf('\n', cursor);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(cursor, end).replace(/\r?\n$/, '');
    if (line.trim() === '') break;
    const isQuoted = /^ {0,3}>/.test(line);
    const contentLine = isQuoted ? line.replace(/^[ \t]{0,3}>[ \t]?/, '') : line;
    if (
      !isQuoted
      && (
        !paragraphActive
        || startsMarkdownBlock(line, paragraphActive)
        || matchZennFence(line)
        || parseZennOpeningLine(line)
      )
    ) break;
    cursor = end;
    paragraphActive = contentLine.trim() !== '' && !startsMarkdownBlock(contentLine, paragraphActive);
  }
  rawLength = cursor;
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

function tokenizeZennBlock(this: TokenizerThis, source: string, rootBoundaryIndex: ZennBoundaryIndex): NyankofaceBlockToken | undefined {
  const firstLineEnd = source.search(/\r?\n/);
  const firstLine = firstLineEnd === -1 ? source : source.slice(0, firstLineEnd);
  const opening = parseZennOpeningLine(firstLine);
  if (!opening || firstLineEnd === -1) return undefined;

  const openingLength = firstLineEnd + (source[firstLineEnd] === '\r' ? 2 : 1);
  const context = zennBoundaryStacks.get(this.lexer)?.at(-1);
  let boundaryIndex = context?.boundaryIndex || rootBoundaryIndex;
  let sourceOffset = context
    ? context.sourceStart + context.sourceLength - source.length
    : rootBoundaryIndex.sourceLength - source.length;
  let absoluteClosing = boundaryIndex.boundaries.get(sourceOffset);
  const rootSourceMatches = rootBoundaryIndex.source.startsWith(firstLine, sourceOffset);
  const lineStart = rootBoundaryIndex.source.lastIndexOf('\n', Math.max(0, sourceOffset - 1)) + 1;
  if (!absoluteClosing && (!rootSourceMatches || sourceOffset !== lineStart)) {
    const localBoundaryIndex = buildZennBoundaryIndex(source);
    const localOffset = localBoundaryIndex.boundaries.keys().next().value;
    if (localOffset === 0) {
      const localClosing = localBoundaryIndex.boundaries.get(localOffset);
      if (localClosing) {
        boundaryIndex = localBoundaryIndex;
        sourceOffset = localOffset;
        absoluteClosing = localClosing;
      }
    }
  }
  if (!absoluteClosing) return undefined;
  const closing = {
    start: absoluteClosing.start - sourceOffset,
    end: absoluteClosing.end - sourceOffset,
  };

  const bodyMarkdown = source
    .slice(openingLength, closing.start)
    .replace(/\r?\n$/, '');
  const raw = source.slice(0, closing.end);
  return {
    type: 'nyankoface-block',
    ...opening,
    raw,
    tokens: blockTokens(this.lexer, bodyMarkdown, boundaryIndex, sourceOffset + openingLength),
  };
}

function startMarkdownBlock(source: string): number | undefined {
  const starts = [
    source.search(/(?:^|\n)(?=[ \t]{0,3}>[ \t]?\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])/i),
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

function createMarkdownExtensions(locale: 'ja' | 'en', boundaryIndex: ZennBoundaryIndex): MarkedExtension {
  return {
    extensions: [{
      name: 'nyankoface-block',
      level: 'block',
      start: startMarkdownBlock,
      tokenizer(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
        return tokenizeGithubAlert.call(this, source) || tokenizeZennBlock.call(this, source, boundaryIndex);
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
  // Marked expands leading tabs before block tokenization; index the same source
  // so custom block offsets remain aligned with the parser's input.
  const normalizedMarkdown = markdown.replace(/\r\n?/g, '\n');
  const markedMarkdown = normalizedMarkdown.replace(/^[ \t]+/gm, expandLeadingTabs);
  const boundaryIndex = buildZennBoundaryIndex(markedMarkdown);
  const parser = new Marked({
    gfm: true,
    breaks: false,
    ...createMarkdownExtensions(locale, boundaryIndex),
  });
  const rendered = parser.parse(markedMarkdown, { async: false, renderer: createMarkdownRenderer(locale) }) as string;
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
