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
const LINK_REFERENCE_LABEL_MAX_LENGTH = 999;
const LINK_REFERENCE_DEFINITION = /^[ \t]{0,3}\[((?:\\.|[^\[\]\\])+)\]:[ \t]*(?:<((?:\\.|[^>\\\n])*)>|([^\s<>]+))(?:[ \t]+(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\((?:\\.|[^()\\\n])*\)))?[ \t]*$/;
const LINK_REFERENCE_PENDING_DESTINATION = /^[ \t]{0,3}\[((?:\\.|[^\[\]\\])+)\]:[ \t]*$/;
const LINK_REFERENCE_DESTINATION = /^[ \t]*(?:<((?:\\.|[^>\\\n])*)>|([^\s<>]+))(?:[ \t]+(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\((?:\\.|[^()\\\n])*\)))?[ \t]*$/;
const LINK_REFERENCE_TITLE = /^[ \t]*(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\((?:\\.|[^()\\\n])*\))[ \t]*$/;

function hasVisibleLinkReferenceLabel(label: string): boolean {
  const normalizedLabel = label.replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g, '$1');
  return Array.from(normalizedLabel).length <= LINK_REFERENCE_LABEL_MAX_LENGTH
    && /\S/.test(normalizedLabel);
}

function hasBalancedLinkReferenceDestination(destination: string): boolean {
  let depth = 0;
  for (let index = 0; index < destination.length; index += 1) {
    if (destination[index] === '\\') {
      index += 1;
      continue;
    }
    if (destination[index] === '(') {
      depth += 1;
    } else if (destination[index] === ')') {
      depth -= 1;
      if (depth < 0) return false;
    }
  }
  return depth === 0;
}

function isLinkReferenceDefinition(line: string): boolean {
  const match = line.match(LINK_REFERENCE_DEFINITION);
  const destination = match?.[2] ?? match?.[3];
  return Boolean(
    match?.[1]
      && destination !== undefined
      && hasVisibleLinkReferenceLabel(match[1])
      && (match[2] !== undefined || hasBalancedLinkReferenceDestination(destination)),
  );
}

function isLinkReferenceDestination(line: string): boolean {
  const match = line.match(LINK_REFERENCE_DESTINATION);
  const destination = match?.[1] ?? match?.[2];
  return Boolean(
    destination !== undefined
      && (match?.[1] !== undefined || hasBalancedLinkReferenceDestination(destination)),
  );
}

function isLinkReferencePendingDestination(line: string): boolean {
  const match = line.match(LINK_REFERENCE_PENDING_DESTINATION);
  return Boolean(match?.[1] && hasVisibleLinkReferenceLabel(match[1]));
}

const RAW_HTML_BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'base', 'basefont', 'blockquote', 'body', 'caption', 'center', 'col', 'colgroup',
  'dd', 'details', 'dialog', 'dir', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
  'form', 'frame', 'frameset', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hr', 'html',
  'iframe', 'legend', 'li', 'link', 'main', 'menu', 'menuitem', 'nav', 'ol', 'optgroup', 'option',
  'p', 'param', 'pre', 'script', 'search', 'section', 'summary', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'hgroup',
  'textarea', 'title', 'tr', 'track', 'ul', 'style', 'noframes',
]);
const RAW_HTML_TAGS_WITH_EXPLICIT_END = new Set(['pre', 'script', 'style', 'textarea']);

type RawHtmlBlockBoundary =
  | { kind: 'blank'; interruptsParagraph: boolean }
  | { kind: 'closing'; pattern: RegExp; interruptsParagraph: boolean };

type RawHtmlBlockResult = RawHtmlBlockBoundary
  | { kind: 'complete'; interruptsParagraph: true };

type RawHtmlBlockState = {
  boundary: RawHtmlBlockBoundary;
  listContentIndent?: number;
};

type ZennBoundary = { start: number; end: number };

type ZennBoundaryIndex = {
  source: string;
  sourceLength: number;
  boundaries: Map<number, ZennBoundary>;
  markdownStarts: number[];
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
type MarkdownLexerState = {
  originalBlockTokens: TokenizerThis['lexer']['blockTokens'];
};

const markdownLexerStates = new WeakMap<object, MarkdownLexerState>();

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

function matchZennFence(line: string, previousLine?: string, listContentIndent?: number): ZennFenceMatch | null {
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
  const previousListPrefix = previousLine?.match(LIST_CONTAINER_PREFIX);
  const continuation = line.match(/^[ \t]+(`{3,}|~{3,})/);
  const continuationContentIndent = listContentIndent
    ?? (previousListPrefix ? textColumns(previousListPrefix[0]) : undefined);
  const continuationIndent = continuation
    ? leadingIndentColumns(continuation[0].slice(0, -continuation[1].length))
    : undefined;
  if (
    continuation
    && continuationContentIndent !== undefined
    && continuationIndent !== undefined
    && continuationIndent >= continuationContentIndent
    && continuationIndent < continuationContentIndent + 4
  ) {
    return {
      token: continuation[1],
      end: continuation[0].length,
      container: { kind: 'list', contentIndent: continuationContentIndent },
    };
  }
  const plain = line.match(/^ {0,3}(`{3,}|~{3,})/);
  return plain ? { token: plain[1], end: plain[0].length } : null;
}

function isValidZennFence(fence: ZennFenceMatch, line: string): boolean {
  const suffix = line.slice(fence.end);
  return fence.token[0] !== '`' || !suffix.includes('`');
}

function stripZennContainerPrefix(line: string): string {
  let content = line;
  for (let depth = 0; depth < 16; depth += 1) {
    const blockquotePrefix = content.match(/^ {0,3}>[ \t]?/);
    if (blockquotePrefix) {
      content = content.slice(blockquotePrefix[0].length);
      continue;
    }
    const listPrefix = content.match(LIST_CONTAINER_PREFIX);
    if (listPrefix) {
      content = content.slice(listPrefix[0].length);
      continue;
    }
    break;
  }
  return content;
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
    if (character === '\\') {
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
    if (character === '|') {
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
    && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim())),
  );
}

function startsMarkdownBlock(line: string, paragraphActive = false, previousLine?: string): boolean {
  if (leadingIndentColumns(line) >= 4) return !paragraphActive;
  const content = line.replace(/^ {0,3}/, '');
  const emptyListMarker = /^(?:[*+-]|\d{1,9}[.)])[ \t]*$/.test(content);
  if (emptyListMarker) return !paragraphActive;
  const orderedList = content.match(/^(\d{1,9})[.)][ \t]+/);
  if (orderedList) return !paragraphActive || Number.parseInt(orderedList[1], 10) === 1;
  const shortSetextUnderline = /^(?:-[ \t]*){1,2}$/.test(content);
  const equalsSetextUnderline = /^={1,}[ \t]*$/.test(content);
  const thematicBreak = /^(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$/;
  return isGfmTableDelimiter(content, previousLine)
    || (shortSetextUnderline && paragraphActive)
    || (equalsSetextUnderline && paragraphActive)
    || (!paragraphActive && isLinkReferenceDefinition(content))
    || thematicBreak.test(content)
    || /^(?:#{1,6}(?:[ \t]+|$)|[*+-][ \t]+|>[ \t]?)/.test(content);
}

function startsParagraphContent(line: string, previousLine?: string): boolean {
  let content = line;
  let hadContainerPrefix = false;
  for (let depth = 0; depth < 16; depth += 1) {
    const normalized = content.replace(/^ {0,3}/, '');
    const listPrefix = normalized.match(LIST_CONTAINER_PREFIX);
    if (listPrefix) {
      hadContainerPrefix = true;
      content = normalized.slice(listPrefix[0].length);
      continue;
    }
    const blockquotePrefix = normalized.match(/^>[ \t]?/);
    if (blockquotePrefix) {
      hadContainerPrefix = true;
      content = normalized.slice(blockquotePrefix[0].length);
      continue;
    }
    const rawHtml = rawHtmlBlockEnd(content);
    return content.trim() !== ''
      && !startsMarkdownBlock(content, false, previousLine)
      && !(rawHtml && (rawHtml.interruptsParagraph || hadContainerPrefix));
  }
  return false;
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
    const whitespaceStart = index;
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
    if (index === whitespaceStart) return undefined;
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

function rawHtmlBlockEnd(line: string): RawHtmlBlockResult | null {
  const trimmed = line.replace(/^[ \t]{0,3}/, '');
  if (trimmed.startsWith('<!--')) return trimmed.includes('-->')
    ? { kind: 'complete', interruptsParagraph: true }
    : { kind: 'closing', pattern: /-->/, interruptsParagraph: true };
  if (trimmed.startsWith('<?')) return trimmed.includes('?>')
    ? { kind: 'complete', interruptsParagraph: true }
    : { kind: 'closing', pattern: /\?>/, interruptsParagraph: true };
  if (/^<!\[CDATA\[/.test(trimmed)) return trimmed.includes(']]>')
    ? { kind: 'complete', interruptsParagraph: true }
    : { kind: 'closing', pattern: /\]\]>/, interruptsParagraph: true };
  if (/^<![A-Z]/.test(trimmed)) return trimmed.includes('>')
    ? { kind: 'complete', interruptsParagraph: true }
    : { kind: 'closing', pattern: />/, interruptsParagraph: true };
  const closingTag = trimmed.match(/^<\/([A-Za-z][A-Za-z0-9-]*)\s*>/);
  if (closingTag) {
    const tagName = closingTag[1].toLowerCase();
    if (!RAW_HTML_BLOCK_TAGS.has(tagName) && trimmed.slice(closingTag[0].length).trim() !== '') return null;
    return {
      kind: 'blank',
      interruptsParagraph: RAW_HTML_BLOCK_TAGS.has(tagName),
    };
  }
  const partialExplicitClosing = trimmed.match(/^<\/([A-Za-z][A-Za-z0-9-]*)(?=\s|$)/);
  if (partialExplicitClosing && RAW_HTML_BLOCK_TAGS.has(partialExplicitClosing[1].toLowerCase())) {
    return { kind: 'blank', interruptsParagraph: true };
  }
  const opening = matchRawHtmlOpening(trimmed);
  if (!opening) {
    const partialExplicitOpening = trimmed.match(/^<([A-Za-z][A-Za-z0-9-]*)(?=\s|$)/);
    if (partialExplicitOpening && RAW_HTML_TAGS_WITH_EXPLICIT_END.has(partialExplicitOpening[1].toLowerCase())) {
      const tagName = partialExplicitOpening[1].toLowerCase();
      return { kind: 'closing', pattern: new RegExp(`</${tagName}>`, 'i'), interruptsParagraph: true };
    }
    if (partialExplicitOpening && RAW_HTML_BLOCK_TAGS.has(partialExplicitOpening[1].toLowerCase())) {
      return { kind: 'blank', interruptsParagraph: true };
    }
    return null;
  }
  const tagName = opening.tagName.toLowerCase();
  const tagSuffix = opening.raw.slice(1 + opening.tagName.length);
  if (tagSuffix.startsWith('/') && !tagSuffix.endsWith('/>')) return null;
  const isBlockTag = RAW_HTML_BLOCK_TAGS.has(tagName);
  const isCompactSelfClosing = /[^ \t]\/>$/.test(opening.raw);
  if (isCompactSelfClosing) {
    if (!isBlockTag && trimmed.slice(opening.raw.length).trim() !== '') return null;
    return { kind: 'blank', interruptsParagraph: isBlockTag };
  }
  const closing = new RegExp(`</${tagName}>`, 'i');
  if (RAW_HTML_TAGS_WITH_EXPLICIT_END.has(tagName)) {
    return closing.test(trimmed.slice(opening.raw.length))
      ? { kind: 'complete', interruptsParagraph: true }
      : { kind: 'closing', pattern: closing, interruptsParagraph: true };
  }
  if (/\/\s+>$/.test(opening.raw)) return null;
  const isSelfClosing = /\/>$/.test(opening.raw);
  if (isSelfClosing) {
    if (!isBlockTag && trimmed.slice(opening.raw.length).trim() !== '') return null;
    return { kind: 'blank', interruptsParagraph: isBlockTag };
  }
  if (!isBlockTag && trimmed.slice(opening.raw.length).trim() !== '') return null;
  return { kind: 'blank', interruptsParagraph: isBlockTag };
}

function buildZennBoundaryIndex(source: string): ZennBoundaryIndex {
  const boundaries = new Map<number, ZennBoundary>();
  const markdownStarts: number[] = [];
  const openings: Array<{ offset: number; listContentIndent?: number }> = [];
  let offset = 0;
  let fenceChar: '`' | '~' | null = null;
  let fenceLength = 0;
  let fenceContainer: ZennFenceContainer | undefined;
  let htmlBlockEnd: RawHtmlBlockState | null = null;
  let listContentIndents: number[] = [];
  let paragraphActive = false;
  let previousLine: string | undefined;

  while (offset < source.length) {
    const newlineIndex = source.indexOf('\n', offset);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(offset, end).replace(/\r?\n$/, '');
    const indentation = leadingIndentColumns(line);
    if (/^ {0,3}>[ \t]?\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]/i.test(line)) {
      markdownStarts.push(offset);
    }

    if (!fenceChar && line.trim() !== '') {
      while (listContentIndents.length && indentation < listContentIndents.at(-1)!) {
        listContentIndents.pop();
      }
    }

    if (!fenceChar) {
      if (htmlBlockEnd) {
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
      if (rawHtml?.kind === 'complete') {
        paragraphActive = false;
        previousLine = line;
        offset = end;
        continue;
      }
      if (rawHtml && (!paragraphActive || rawHtml.interruptsParagraph)) {
        const listPrefix = line.match(LIST_CONTAINER_PREFIX);
        htmlBlockEnd = {
          boundary: rawHtml,
          listContentIndent: listPrefix ? textColumns(listPrefix[0]) : listContentIndents.at(-1),
        };
        paragraphActive = false;
        previousLine = line;
        offset = end;
        continue;
      }
      if (!rawHtml && indentation < 4 && /^\s*(?:<!--|<\?|<![A-Z])/.test(line)) {
        paragraphActive = false;
        previousLine = line;
        offset = end;
        continue;
      }
    }

    const fence = matchZennFence(line, previousLine, listContentIndents.at(-1));

    if (fenceChar && fenceContainer && !continuesZennFenceContainer(line, fenceContainer)) {
      fenceChar = null;
      fenceLength = 0;
      fenceContainer = undefined;
    }

    if (!fenceChar && line.trim() !== '') {
      const listPrefix = line.match(LIST_CONTAINER_PREFIX);
      if (listPrefix && (!paragraphActive || startsMarkdownBlock(line, paragraphActive, previousLine))) {
        const contentIndent = textColumns(listPrefix[0]);
        while (listContentIndents.length && contentIndent <= listContentIndents.at(-1)!) {
          listContentIndents.pop();
        }
        listContentIndents.push(contentIndent);
      }
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
    } else if (fence && isValidZennFence(fence, line)) {
      fenceChar = fence.token[0] as '`' | '~';
      fenceLength = fence.token.length;
      fenceContainer = fence.container;
      paragraphActive = false;
    } else if (
      parseZennOpeningLine(stripZennContainerPrefix(line))
      && (!line.match(LIST_CONTAINER_PREFIX) || startsMarkdownBlock(line, paragraphActive, previousLine))
    ) {
      const listPrefix = line.match(LIST_CONTAINER_PREFIX);
      openings.push({ offset, listContentIndent: listPrefix ? textColumns(listPrefix[0]) : listContentIndents.at(-1) });
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
        markdownStarts.push(opening.offset);
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
  markdownStarts.sort((left, right) => left - right);
  return { source, sourceLength: source.length, boundaries, markdownStarts };
}

function installMarkdownBlockTokens(lexer: TokenizerThis['lexer']): void {
  if (markdownLexerStates.has(lexer)) return;
  const originalBlockTokens = lexer.blockTokens.bind(lexer);
  markdownLexerStates.set(lexer, { originalBlockTokens });
  lexer.blockTokens = ((source: string, tokens?: Token[]) => {
    const boundaryIndex = buildZennBoundaryIndex(source);
    const stack = zennBoundaryStacks.get(lexer) || [];
    stack.push({ boundaryIndex, sourceStart: 0, sourceLength: source.length });
    zennBoundaryStacks.set(lexer, stack);
    try {
      return originalBlockTokens(source, tokens);
    } finally {
      stack.pop();
      if (stack.length === 0) zennBoundaryStacks.delete(lexer);
    }
  }) as typeof lexer.blockTokens;
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
    const state = markdownLexerStates.get(lexer);
    return state ? state.originalBlockTokens(source) : lexer.blockTokens(source);
  } finally {
    lexer.state.top = previousTop;
    stack.pop();
    if (stack.length === 0) zennBoundaryStacks.delete(lexer);
  }
}

function hasQuotedZennCloser(source: string, cursor: number, listContentIndent?: number): boolean {
  let depth = 1;
  const listContentIndents: Array<number | undefined> = [listContentIndent];
  let fenceChar: '`' | '~' | null = null;
  let fenceLength = 0;
  let fenceContainer: ZennFenceContainer | undefined;
  let htmlBoundary: RawHtmlBlockBoundary | null = null;
  let previousLine: string | undefined;
  let offset = cursor;
  while (offset < source.length) {
    const newlineIndex = source.indexOf('\n', offset);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(offset, end).replace(/\r?\n$/, '');
    if (line.trim() === '') return false;
    const isQuoted = /^ {0,3}>/.test(line);
    if (!isQuoted) return false;
    const contentLine = isQuoted ? line.replace(/^[ \t]{0,3}>[ \t]?/, '') : line;
    const contentFence = matchZennFence(
      contentLine,
      previousLine,
      fenceContainer?.kind === 'list' ? fenceContainer.contentIndent : listContentIndents.at(-1),
    );
    if (htmlBoundary !== null) {
      const endsHtml = htmlBoundary.kind === 'blank'
        ? contentLine.trim() === ''
        : htmlBoundary.pattern.test(contentLine);
      if (endsHtml) htmlBoundary = null;
    } else if (fenceChar !== null) {
      const closesFence = Boolean(
        contentFence
        && contentFence.token[0] === fenceChar
        && contentFence.token.length >= fenceLength
        && sameZennFenceContainer(contentFence.container, fenceContainer)
        && contentLine.slice(contentFence.end).trim() === '',
      );
      if (closesFence) {
        fenceChar = null;
        fenceLength = 0;
        fenceContainer = undefined;
      }
    } else {
      const normalizedLine = stripZennContainerPrefix(contentLine);
      const rawHtml = rawHtmlBlockEnd(normalizedLine);
      if (rawHtml?.kind === 'complete') {
        // The line is entirely HTML; directives inside it do not nest.
      } else if (rawHtml) {
        htmlBoundary = rawHtml;
      } else if (contentFence && isValidZennFence(contentFence, contentLine)) {
        fenceChar = contentFence.token[0] as '`' | '~';
        fenceLength = contentFence.token.length;
        fenceContainer = contentFence.container;
      } else if (parseZennOpeningLine(normalizedLine)) {
        const listPrefix = contentLine.match(LIST_CONTAINER_PREFIX);
        depth += 1;
        listContentIndents.push(listPrefix ? textColumns(listPrefix[0]) : undefined);
      } else if (isZennClosingLine(normalizedLine, listContentIndents.at(-1))) {
        depth -= 1;
        listContentIndents.pop();
        if (depth === 0) return true;
      }
    }
    previousLine = contentLine;
    offset = end;
  }
  return false;
}

function tokenizeGithubAlert(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
  const header = source.match(/^ {0,3}>[ \t]?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\r?\n|$)/);
  if (!header) return undefined;

  const boundaryContext = zennBoundaryStacks.get(this.lexer)?.at(-1);
  const zennBoundaryIndex = boundaryContext?.boundaryIndex || buildZennBoundaryIndex(source);
  const zennSourceOffset = boundaryContext
    ? boundaryContext.sourceStart + boundaryContext.sourceLength - source.length
    : 0;
  let rawLength = header[0].length;
  let cursor = rawLength;
  let paragraphActive = true;
  let previousLine: string | undefined;
  let quotedFenceChar: '`' | '~' | null = null;
  let quotedFenceLength = 0;
  let quotedFenceContainer: ZennFenceContainer | undefined;
  let quotedHtmlBoundary: RawHtmlBlockBoundary | null = null;
  let quotedLinkReferenceDefinition = false;
  let quotedLinkReferenceNeedsDestination = false;
  let quotedZennOpenings: Array<{ listContentIndent?: number }> = [];
  let hasAlertBody = false;
  while (cursor < source.length) {
    const newlineIndex = source.indexOf('\n', cursor);
    const end = newlineIndex === -1 ? source.length : newlineIndex + 1;
    const line = source.slice(cursor, end).replace(/\r?\n$/, '');
    if (line.trim() === '') break;
    const isQuoted = /^ {0,3}>/.test(line);
    const contentLine = isQuoted ? line.replace(/^[ \t]{0,3}>[ \t]?/, '') : line;
    const contentFence = isQuoted
      ? matchZennFence(
        contentLine,
        previousLine,
        quotedFenceContainer?.kind === 'list' ? quotedFenceContainer.contentIndent : undefined,
      )
      : null;
    const unquotedFence = isQuoted ? null : matchZennFence(line);
    const validUnquotedFence = Boolean(unquotedFence && isValidZennFence(unquotedFence, line));
    if (
      !isQuoted
      && (
        quotedFenceChar !== null
        || quotedHtmlBoundary !== null
        || (!paragraphActive && !quotedLinkReferenceNeedsDestination)
        || startsMarkdownBlock(line, paragraphActive, previousLine)
        || validUnquotedFence
        || (parseZennOpeningLine(line) && zennBoundaryIndex.boundaries.has(zennSourceOffset + cursor))
        || rawHtmlBlockEnd(line)?.interruptsParagraph
      )
    ) break;
    cursor = end;
    if (quotedHtmlBoundary !== null) {
      quotedLinkReferenceDefinition = false;
      quotedLinkReferenceNeedsDestination = false;
      const endsHtml = quotedHtmlBoundary.kind === 'blank'
        ? contentLine.trim() === ''
        : quotedHtmlBoundary.pattern.test(contentLine);
      if (endsHtml) quotedHtmlBoundary = null;
      paragraphActive = false;
    } else if (quotedFenceChar !== null) {
      quotedLinkReferenceDefinition = false;
      quotedLinkReferenceNeedsDestination = false;
      const closesFence = Boolean(
        contentFence
        && contentFence.token[0] === quotedFenceChar
        && contentFence.token.length >= quotedFenceLength
        && sameZennFenceContainer(contentFence.container, quotedFenceContainer)
        && contentLine.slice(contentFence.end).trim() === '',
      );
      if (closesFence) {
        quotedFenceChar = null;
        quotedFenceLength = 0;
        quotedFenceContainer = undefined;
      }
      paragraphActive = false;
    } else if (contentFence && isValidZennFence(contentFence, contentLine)) {
      quotedLinkReferenceDefinition = false;
      quotedLinkReferenceNeedsDestination = false;
      quotedFenceChar = contentFence.token[0] as '`' | '~';
      quotedFenceLength = contentFence.token.length;
      quotedFenceContainer = contentFence.container;
      paragraphActive = false;
    } else {
      const rawHtml = rawHtmlBlockEnd(stripZennContainerPrefix(contentLine));
      if (rawHtml?.kind === 'complete') {
        quotedLinkReferenceDefinition = false;
        quotedLinkReferenceNeedsDestination = false;
        paragraphActive = false;
      } else if (rawHtml && (!paragraphActive || rawHtml.interruptsParagraph || !hasAlertBody)) {
        quotedLinkReferenceDefinition = false;
        quotedLinkReferenceNeedsDestination = false;
        quotedHtmlBoundary = rawHtml;
        paragraphActive = false;
      } else {
        const zennContentLine = stripZennContainerPrefix(contentLine);
        const zennOpening = parseZennOpeningLine(zennContentLine);
        const zennListPrefix = contentLine.match(LIST_CONTAINER_PREFIX);
        const zennListContentIndent = zennListPrefix ? textColumns(zennListPrefix[0]) : undefined;
        const zennClosing = quotedZennOpenings.length > 0
          && isZennClosingLine(zennContentLine, quotedZennOpenings.at(-1)?.listContentIndent);
        if (zennClosing) {
          quotedZennOpenings = quotedZennOpenings.slice(0, -1);
          quotedLinkReferenceDefinition = false;
          quotedLinkReferenceNeedsDestination = false;
          paragraphActive = false;
        } else if (zennOpening && hasQuotedZennCloser(source, cursor, zennListContentIndent)) {
          quotedZennOpenings = [
            ...quotedZennOpenings,
            { listContentIndent: zennListContentIndent },
          ];
          quotedLinkReferenceDefinition = false;
          quotedLinkReferenceNeedsDestination = false;
          paragraphActive = false;
        } else {
          const paragraphContent = startsParagraphContent(contentLine, previousLine);
          const linkReferenceTitle: boolean = quotedLinkReferenceDefinition && LINK_REFERENCE_TITLE.test(contentLine);
          const linkReferenceDestination: boolean = quotedLinkReferenceNeedsDestination && isLinkReferenceDestination(contentLine);
          const linkReferenceDefinition: boolean = isQuoted
            && (!paragraphActive || !hasAlertBody)
            && isLinkReferenceDefinition(contentLine);
          const linkReferencePendingDestination: boolean = isQuoted
            && (!paragraphActive || !hasAlertBody)
            && isLinkReferencePendingDestination(contentLine);
          paragraphActive = contentLine.trim() !== ''
            && !linkReferenceTitle
            && !linkReferenceDestination
            && !linkReferenceDefinition
            && !linkReferencePendingDestination
            && (paragraphContent || !startsMarkdownBlock(contentLine, paragraphActive, previousLine));
          quotedLinkReferenceDefinition = linkReferenceDestination || linkReferenceDefinition;
          quotedLinkReferenceNeedsDestination = linkReferencePendingDestination;
        }
      }
    }
    hasAlertBody = true;
    previousLine = contentLine;
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

function findNextMarkdownStart(
  markdownStarts: number[],
  currentOffset: number,
  sourceEnd: number,
  includeCurrent: boolean,
): number | undefined {
  let low = 0;
  let high = markdownStarts.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (includeCurrent
      ? markdownStarts[middle] < currentOffset
      : markdownStarts[middle] <= currentOffset) {
      low = middle + 1;
    }
    else high = middle;
  }
  const nextStart = markdownStarts[low];
  if (nextStart === undefined || nextStart >= sourceEnd) return undefined;
  return nextStart;
}

function startMarkdownBlock(
  this: { lexer?: TokenizerThis['lexer'] },
  source: string,
  rootBoundaryIndex: ZennBoundaryIndex,
): number | undefined {
  const lexer = this.lexer;
  if (!lexer) return undefined;
  const context = zennBoundaryStacks.get(lexer)?.at(-1);
  if (context) {
    const remainingLength = source.length + 1;
    if (remainingLength > context.sourceLength) return undefined;
    const currentOffset = context.sourceStart + context.sourceLength - remainingLength;
    const sourceEnd = context.sourceStart + context.sourceLength;
    const nextStart = findNextMarkdownStart(
      context.boundaryIndex.markdownStarts,
      currentOffset,
      sourceEnd,
      false,
    );
    return nextStart === undefined ? undefined : nextStart - currentOffset - 1;
  }

  const remainingLength = source.length + 1;
  if (remainingLength > rootBoundaryIndex.sourceLength) return undefined;
  const currentOffset = rootBoundaryIndex.sourceLength - remainingLength;
  const nextStart = findNextMarkdownStart(
    rootBoundaryIndex.markdownStarts,
    currentOffset,
    rootBoundaryIndex.sourceLength,
    false,
  );
  return nextStart === undefined ? undefined : nextStart - currentOffset - 1;
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
      start(source: string): number | undefined {
        return startMarkdownBlock.call(this, source, boundaryIndex);
      },
      tokenizer(this: TokenizerThis, source: string): NyankofaceBlockToken | undefined {
        installMarkdownBlockTokens(this.lexer);
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

export function renderMarkdownBody(markdown: string, urls?: ReadmeRenderUrls): string {
  return renderMarkdown(markdown, urls);
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
