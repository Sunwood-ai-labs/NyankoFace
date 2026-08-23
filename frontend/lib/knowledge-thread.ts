export interface KnowledgeThreadSource {
  label: string;
  url: string;
}

export interface KnowledgeThreadMetadata {
  part?: string;
  theme?: string;
  rules: string[];
  sources: KnowledgeThreadSource[];
}

export interface KnowledgeThreadPost {
  number: number;
  name: string;
  role?: string;
  id?: string;
  postedAt?: string;
  bodyMarkdown: string;
  replyTo: number[];
}

export interface KnowledgeThread {
  metadata: KnowledgeThreadMetadata;
  posts: KnowledgeThreadPost[];
}

type Frontmatter = Record<string, unknown>;

function record(value: unknown): Frontmatter | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Frontmatter
    : undefined;
}

function trimSurroundingBlankLines(value: string): string {
  if (!value.trim()) return '';
  return value
    .replace(/^(?:[ \t]*\r?\n)+/, '')
    .replace(/(?:\r?\n[ \t]*)+$/, '');
}

function rawMarkdownBodyValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return '';
}
const utf8Encoder = new TextEncoder();
function utf8ByteLength(value: string): number {
  return utf8Encoder.encode(value).length;
}
function truncateUtf8(value: string, maxBytes: number): string {
  if (value.length <= maxBytes && utf8ByteLength(value) <= maxBytes) return value;
  let low = 0;
  let high = Math.min(value.length, maxBytes) + 1;
  while (low + 1 < high) {
    const middle = Math.floor((low + high) / 2);
    if (utf8ByteLength(value.slice(0, middle)) <= maxBytes) {
      low = middle;
    } else {
      high = middle;
    }
  }
  const end = low > 0 && value.charCodeAt(low - 1) >= 0xd800 && value.charCodeAt(low - 1) <= 0xdbff
    ? low - 1
    : low;
  return value.slice(0, end);
}
function boundedStringValue(
  value: unknown,
  maxBytes = MAX_THREAD_METADATA_FIELD_BYTES,
): string | undefined {
  let rawValue: string;
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    rawValue = value.toISOString();
  } else if (typeof value === 'string') {
    rawValue = value.slice(0, maxBytes);
  } else if (typeof value === 'number') {
    rawValue = String(value);
  } else {
    return undefined;
  }
  const normalized = rawValue.trim();
  return normalized ? truncateUtf8(normalized, maxBytes) : undefined;
}
function list(value: unknown, limit = Number.MAX_SAFE_INTEGER): string[] {
  if (Array.isArray(value)) {
    const values: string[] = [];
    let usedBytes = 0;
    let consumed = 0;
    for (const item of value) {
      if (consumed >= limit || usedBytes >= MAX_THREAD_REPLY_LIST_BYTES) break;
      consumed += 1;
      const remainingBytes = MAX_THREAD_REPLY_LIST_BYTES - usedBytes;
      const normalized = boundedStringValue(item, remainingBytes);
      if (!normalized) continue;
      const itemBytes = utf8ByteLength(normalized);
      if (itemBytes > remainingBytes) break;
      usedBytes += itemBytes;
      values.push(normalized);
    }
    return values;
  }
  const single = boundedStringValue(value, MAX_THREAD_REPLY_LIST_BYTES);
  if (!single) return [];
  const values: string[] = [];
  let start = 0;
  for (let index = 0; index <= single.length && values.length < limit; index += 1) {
    const atEnd = index === single.length;
    const isSeparator = !atEnd && (single[index] === ',' || single[index] === '\r' || single[index] === '\n');
    if (!atEnd && !isSeparator) continue;
    const item = single.slice(start, index).trim();
    if (item) values.push(item);
    if (!atEnd && single[index] === '\r' && single[index + 1] === '\n') index += 1;
    start = index + 1;
  }
  return values;
}

const MAX_POST_NUMBER = 1_000_000;
const MAX_THREAD_POSTS = 2_048;
const MAX_THREAD_REPLIES = 256;
const MAX_THREAD_POST_BODY_BYTES = 64 * 1024;
const MAX_THREAD_BODY_BYTES = 1024 * 1024;
const MAX_THREAD_METADATA_FIELD_BYTES = 4 * 1024;
const MAX_THREAD_METADATA_BYTES = 256 * 1024;
const MAX_THREAD_POST_METADATA_FIELD_BYTES = MAX_THREAD_METADATA_FIELD_BYTES;
const MAX_THREAD_POST_METADATA_BYTES = MAX_THREAD_METADATA_BYTES;
const MAX_THREAD_REPLY_LIST_BYTES = 16 * 1024;
const MAX_THREAD_REPLY_TARGETS = 8_192;
const MAX_MARKDOWN_LINK_LABEL_DEPTH = 32;
const MAX_THREAD_INTEGER_TEXT_BYTES = 32;
const MAX_THREAD_RULES = 256;
const MAX_THREAD_SOURCES = 256;
type ByteBudget = {
  used: number;
  limit: number;
};
type ReplyTargetBudget = {
  used: number;
  limit: number;
};

function takeMetadataString(value: unknown, budget: ByteBudget): string | undefined {
  const normalized = boundedStringValue(value);
  if (!normalized) return undefined;
  const bytes = utf8ByteLength(normalized);
  if (budget.used + bytes > budget.limit) return undefined;
  budget.used += bytes;
  return normalized;
}

function normalizeMetadataList(value: unknown, limit: number, budget: ByteBudget): string[] {
  const values = Array.isArray(value)
    ? value.slice(0, limit)
    : (() => {
      const single = boundedStringValue(value);
      return single ? single.split(/\r?\n|,/) : [];
    })();
  const normalized: string[] = [];
  for (const item of values) {
    const itemValue = takeMetadataString(item, budget);
    if (itemValue) {
      normalized.push(itemValue);
    }
    if (budget.used >= budget.limit) break;
  }
  return normalized;
}

function positiveInteger(value: unknown): number | undefined {
  const number = typeof value === 'number'
    ? value
    : typeof value === 'string'
      && value.length <= MAX_THREAD_INTEGER_TEXT_BYTES
      && /^[+]?\d+$/.test(value.trim())
      ? Number(value.trim())
      : undefined;
  if (number === undefined) return undefined;
  return Number.isSafeInteger(number) && number > 0 && number <= MAX_POST_NUMBER ? number : undefined;
}
function threadPostsValue(frontmatter: Frontmatter, metadata?: Frontmatter): unknown {
  return metadata?.posts ?? frontmatter.posts ?? frontmatter.thread_posts;
}

const SANITIZED_NON_TEXT_HTML_TAGS = new Set([
  'code', 'pre', 'script', 'style', 'textarea', 'option', 'title', 'noembed', 'noframes', 'plaintext',
]);

const SANITIZED_RAW_TEXT_HTML_TAGS = new Set([
  'script', 'style', 'textarea', 'option', 'title', 'noembed', 'noframes', 'plaintext',
]);

const HTML_BLOCK_TYPE_1_TAGS = new Set(['pre', 'script', 'style', 'textarea']);

const HTML_BLOCK_LINE_PATTERN = /^\s{0,3}(?:<!--|<\?|<!\[CDATA\[|<![A-Z]|<\/?(?:address|article|aside|blockquote|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|nav|ol|p|pre|script|section|style|summary|table|tbody|td|tfoot|th|thead|title|tr|ul)(?:\s|\/?>))/i;
const HTML_BLOCK_TAG_PATTERN = /^\s{0,3}<\s*(\/?)\s*(address|article|aside|blockquote|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|nav|ol|p|pre|script|section|style|summary|table|tbody|td|tfoot|th|thead|title|tr|ul)\b[^>]*>/i;
const THEMATIC_BREAK_LINE_PATTERN = /^\s{0,3}(?:(?:\*[\t ]*){3,}|(?:-[\t ]*){3,}|(?:_[\t ]*){3,})$/;
const MARKDOWN_EMAIL_AUTOLINK_PATTERN = /^[A-Za-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+(?![-_])$/;

function findHtmlTagEnd(value: string, start: number): number {
  let quote = '';
  for (let index = start + 1; index < value.length; index += 1) {
    const character = value[index];
    if (quote) {
      if (character === quote) quote = '';
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
    } else if (character === '>') {
      return index;
    }
  }
  return -1;
}

function findRawHtmlTokenEnd(value: string, start: number): number {
  if (value.startsWith('<?', start)) {
    const end = value.indexOf('?>', start + 2);
    if (end < 0) return -1;
    const rawToken = value.slice(start, end + 2);
    return /^<\?[A-Za-z][A-Za-z0-9:_-]*(?:\s|\?|$)/.test(rawToken) ? end + 1 : -1;
  }
  if (value.startsWith('<![CDATA[', start)) {
    const end = value.indexOf(']]>', start + 9);
    return end >= 0 ? end + 2 : -1;
  }
  const end = findHtmlTagEnd(value, start);
  if (end < 0) return -1;
  const rawToken = value.slice(start, end + 1);
  return /^<!DOCTYPE(?:\s|>)/i.test(rawToken) ? end : -1;
}
function parseHtmlTag(
  value: string,
  start: number,
  end: number,
): { name: string; closing: boolean; selfClosing: boolean } | undefined {
  const rawTag = value.slice(start, end + 1);
  const match = /^<\s*(\/?)\s*([A-Za-z][A-Za-z0-9:-]*)\b/.exec(rawTag);
  if (!match) return undefined;

  const attributes = rawTag.slice(match[0].length, -1).trim();
  if (match[1]) {
    if (attributes) return undefined;
  } else {
    const attributeText = /\/\s*$/.test(attributes)
      ? attributes.replace(/\/\s*$/, '').trim()
      : attributes;
    let index = 0;
    while (index < attributeText.length) {
      while (index < attributeText.length && /\s/.test(attributeText[index])) index += 1;
      if (index >= attributeText.length) break;
      const attribute = /^[A-Za-z_:][A-Za-z0-9:._-]*/.exec(attributeText.slice(index));
      if (!attribute) return undefined;
      index += attribute[0].length;
      while (index < attributeText.length && /\s/.test(attributeText[index])) index += 1;
      if (attributeText[index] !== '=') continue;
      index += 1;
      while (index < attributeText.length && /\s/.test(attributeText[index])) index += 1;
      const quote = attributeText[index];
      if (quote === '"' || quote === "'") {
        index += 1;
        const closingQuote = attributeText.indexOf(quote, index);
        if (closingQuote < 0) return undefined;
        index = closingQuote + 1;
      } else {
        const unquoted = /^[^\s"'`=<>]+/.exec(attributeText.slice(index));
        if (!unquoted) return undefined;
        index += unquoted[0].length;
      }
    }
  }

  return {
    name: match[2].toLowerCase(),
    closing: Boolean(match[1]),
    selfClosing: /\/\s*>$/.test(rawTag),
  };
}
function stripHiddenHtml(value: string): string {
  const visible: string[] = [];
  let hiddenTag = '';
  let hiddenDepth = 0;
  let hiddenRawText = false;
  let index = 0;

  while (index < value.length) {
    if (hiddenTag) {
      if (value[index] !== '<') {
        index += 1;
        continue;
      }
      const tagEnd = findHtmlTagEnd(value, index);
      if (tagEnd < 0) break;
      const tag = parseHtmlTag(value, index, tagEnd);
      if (tag?.name === hiddenTag) {
        if (tag.closing) {
          if (hiddenRawText || hiddenDepth === 1) {
            hiddenTag = '';
            hiddenDepth = 0;
            hiddenRawText = false;
          } else {
            hiddenDepth -= 1;
          }
        } else if (!hiddenRawText && !tag.selfClosing) {
          hiddenDepth += 1;
        }
      }
      index = tagEnd + 1;
      continue;
    }

    if (value.startsWith('<!--', index)) {
      const commentEnd = value.indexOf('-->', index + 4);
      index = commentEnd >= 0 ? commentEnd + 3 : value.length;
      continue;
    }

    let backslashCount = 0;
    for (
      let cursor = index - 1;
      cursor >= 0 && value[cursor] === '\\';
      cursor -= 1
    ) {
      backslashCount += 1;
    }
    if (backslashCount % 2 === 1) {
      visible.push(value[index]);
      index += 1;
      continue;
    }

    const next = value[index + 1] || '';
    if (value[index] !== '<' || !/[\/!?A-Za-z]/.test(next)) {
      visible.push(value[index]);
      index += 1;
      continue;
    }

    if (next === '?' || next === '!') {
      const rawEnd = findRawHtmlTokenEnd(value, index);
      if (rawEnd < 0) {
        visible.push(value.slice(index));
        break;
      }
      index = rawEnd + 1;
      continue;
    }

    const tagEnd = findHtmlTagEnd(value, index);
    if (tagEnd < 0) {
      visible.push(value.slice(index));
      break;
    }
    const tag = parseHtmlTag(value, index, tagEnd);
    if (tag && !tag.closing && SANITIZED_NON_TEXT_HTML_TAGS.has(tag.name)) {
      if (!tag.selfClosing) {
        hiddenTag = tag.name;
        hiddenDepth = 1;
        hiddenRawText = SANITIZED_RAW_TEXT_HTML_TAGS.has(tag.name);
      }
      index = tagEnd + 1;
      continue;
    }

    visible.push(value.slice(index, tagEnd + 1));
    index = tagEnd + 1;
  }

  return visible.join('');
}
function findMarkdownDelimiterEnds(value: string, open: string, close: string): Map<number, number> {
  const stack: number[] = [];
  const ends = new Map<number, number>();
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === '\\') {
      index += 1;
      continue;
    }
    if (value[index] === open) {
      stack.push(index);
    } else if (value[index] === close && stack.length > 0) {
      const start = stack.pop();
      if (start !== undefined) ends.set(start, index);
    }
  }
  return ends;
}
function normalizeMarkdownReferenceLabel(value: string): string {
  return value.replace(/\\(.)/g, '$1').replace(/\s+/g, ' ').trim().toLowerCase();
}
function hasVisibleMarkdownReferenceLabel(value: string): boolean {
  const normalizedLabel = normalizeMarkdownReferenceLabel(value);
  return Array.from(normalizedLabel).length <= 999 && /\S/.test(normalizedLabel);
}

function isValidInlineLinkContent(value: string): boolean {
  let index = 0;
  const skipWhitespace = (): void => {
    while (index < value.length && /\s/.test(value[index])) index += 1;
  };

  skipWhitespace();
  if (index === value.length) return true;

  if (value[index] === '<') {
    index += 1;
    let closed = false;
    while (index < value.length) {
      if (value[index] === '\\') {
        index += 2;
        continue;
      }
      if (value[index] === '\r' || value[index] === '\n') return false;
      if (value[index] === '>') {
        closed = true;
        index += 1;
        break;
      }
      index += 1;
    }
    if (!closed) return false;
  } else {
    while (index < value.length && !/[\s<]/.test(value[index])) index += 1;
  }

  skipWhitespace();
  if (index === value.length) return true;

  const titleDelimiter = value[index];
  if (titleDelimiter === '"' || titleDelimiter === "'") {
    index += 1;
    let closed = false;
    while (index < value.length) {
      if (value[index] === '\\') {
        index += 2;
        continue;
      }
      if (value[index] === titleDelimiter) {
        closed = true;
        index += 1;
        break;
      }
      index += 1;
    }
    if (!closed) return false;
  } else if (titleDelimiter === '(') {
    index += 1;
    let closed = false;
    while (index < value.length) {
      if (value[index] === '\\') {
        index += 2;
        continue;
      }
      if (value[index] === ')') {
        closed = true;
        index += 1;
        break;
      }
      index += 1;
    }
    if (!closed) return false;
  } else {
    return false;
  }

  skipWhitespace();
  return index === value.length;
}

function findMarkdownLinkDelimiterEnds(value: string): Map<number, number> {
  const stack: number[] = [];
  const ends = new Map<number, number>();
  let quote = '';

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (quote) {
      if (character === '\\') {
        index += 1;
      } else if (character === quote) {
        quote = '';
      }
      continue;
    }
    if (character === '\\') {
      index += 1;
      continue;
    }
    if (
      stack.length > 0
      && (character === '"' || character === "'")
      && /\s/.test(value[index - 1] || '')
    ) {
      quote = character;
      continue;
    }
    if (character === '(') {
      stack.push(index);
    } else if (character === ')' && stack.length > 0) {
      const start = stack.pop();
      if (start !== undefined) ends.set(start, index);
    }
  }
  return ends;
}

function isEscapedMarkdownCharacter(value: string, index: number): boolean {
  let backslashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && value[cursor] === '\\'; cursor -= 1) {
    backslashCount += 1;
  }
  return backslashCount % 2 === 1;
}

const MARKDOWN_REFERENCE_DEFINITION_LINE_PATTERN = /^[ \t]{0,3}\[((?:\\.|[^\[\]\\])+)\]:[ \t]*(?:<[^>\r\n]+>|(?:[^\s\r\n()]|\([^()\r\n]*\))+)(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?[ \t]*$/;
function isMarkdownReferenceDefinitionLine(value: string): boolean {
  const match = MARKDOWN_REFERENCE_DEFINITION_LINE_PATTERN.exec(value);
  return match !== null && hasVisibleMarkdownReferenceLabel(match[1]);
}

function escapeMarkdownHtmlTagOpeners(value: string): string {
  let escaped = '';
  let backslashes = 0;
  for (const character of value) {
    if (character === '<' && backslashes % 2 === 0) escaped += '\\';
    escaped += character;
    backslashes = character === '\\' ? backslashes + 1 : 0;
  }
  return escaped;
}

function stripMarkdownLinkDestinations(value: string, depth = 0): string {
  let visible = '';
  const bracketEnds = findMarkdownDelimiterEnds(value, '[', ']');
  const parenthesisEnds = findMarkdownLinkDelimiterEnds(value);
  const referenceDefinitionPattern = /^[ \t]{0,3}\[((?:\\.|[^\[\]\\])+)\]:[ \t]*(?:\r?\n[ \t]+)?(?:<[^>\r\n]+>|(?:[^\s\r\n()]|\([^()\r\n]*\))+)(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?(?:\r?\n[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?[ \t]*$/gm;
  const referenceDefinitions = new Set(
    [...value.matchAll(referenceDefinitionPattern)]
      .filter((match) => hasVisibleMarkdownReferenceLabel(match[1]))
      .map((match) => normalizeMarkdownReferenceLabel(match[1])),
  );
  let index = 0;
  while (index < value.length) {
    const isImage = value[index] === '!'
      && value[index + 1] === '['
      && !isEscapedMarkdownCharacter(value, index);
    const labelStart = value[index] === '['
      ? index
      : isImage
        ? index + 1
        : -1;
    if (labelStart >= 0) {
      const labelEnd = bracketEnds.get(labelStart) ?? -1;
      if (labelEnd >= 0 && value[labelEnd + 1] === '(') {
        const destinationEnd = parenthesisEnds.get(labelEnd + 1) ?? -1;
        if (destinationEnd >= 0) {
          const destination = value.slice(labelEnd + 2, destinationEnd);
          if (isValidInlineLinkContent(destination)) {
            if (!isImage) {
              visible += depth >= MAX_MARKDOWN_LINK_LABEL_DEPTH
                ? value.slice(index, labelEnd + 1)
                : stripMarkdownLinkDestinations(value.slice(index, labelEnd + 1), depth + 1);
            }
            index = destinationEnd + 1;
            continue;
          }
          visible += value.slice(index, labelEnd + 2)
            + escapeMarkdownHtmlTagOpeners(destination)
            + ')';
          index = destinationEnd + 1;
          continue;
        }
      }
      const referenceEnd = labelEnd >= 0 && value[labelEnd + 1] === '['
        ? bracketEnds.get(labelEnd + 1) ?? -1
        : -1;
      const imageLabel = labelEnd >= 0
        ? normalizeMarkdownReferenceLabel(value.slice(labelStart + 1, labelEnd))
        : '';
      const referenceLabel = referenceEnd >= 0
        ? normalizeMarkdownReferenceLabel(value.slice(labelEnd + 2, referenceEnd))
        : '';
      if (
        labelEnd >= 0
        && (
          (referenceEnd >= 0 && referenceDefinitions.has(referenceLabel || imageLabel))
          || (isImage && referenceDefinitions.has(imageLabel))
        )
      ) {
        if (!isImage) {
          visible += depth >= MAX_MARKDOWN_LINK_LABEL_DEPTH
            ? value.slice(index, labelEnd + 1)
            : stripMarkdownLinkDestinations(value.slice(index, labelEnd + 1), depth + 1);
        }
        index = referenceEnd >= 0 ? referenceEnd + 1 : labelEnd + 1;
        continue;
      }
    }
    visible += value[index];
    index += 1;
  }
  return visible.replace(referenceDefinitionPattern, (match, label) =>
    hasVisibleMarkdownReferenceLabel(label) ? '' : match,
  );
}
function stripHtmlTags(value: string): string {
  const visible: string[] = [];
  let index = 0;

  while (index < value.length) {
    if (value[index] !== '<') {
      visible.push(value[index]);
      index += 1;
      continue;
    }

    let backslashCount = 0;
    for (
      let cursor = index - 1;
      cursor >= 0 && value[cursor] === '\\';
      cursor -= 1
    ) {
      backslashCount += 1;
    }
    if (backslashCount % 2 === 1) {
      visible.push(value[index]);
      index += 1;
      continue;
    }

    const next = value[index + 1] || '';
    const afterSlash = next === '/' ? value[index + 2] || '' : next;
    if (!/[A-Za-z]/.test(afterSlash)) {
      if (next === '?' || next === '!') {
        const rawEnd = findRawHtmlTokenEnd(value, index);
        if (rawEnd < 0) {
          visible.push(value.slice(index));
          break;
        }
        index = rawEnd + 1;
        continue;
      }
      visible.push(value[index]);
      index += 1;
      continue;
    }

    const tagEnd = findHtmlTagEnd(value, index);
    if (tagEnd < 0) {
      visible.push(value.slice(index));
      break;
    }

    const autolinkContent = value.slice(index + 1, tagEnd);
    const uriSchemePrefix = /^[A-Za-z][A-Za-z0-9+.-]{1,31}:/.test(autolinkContent);
    const invalidUriWhitespace = uriSchemePrefix && /[\x00-\x20\x7f]/.test(autolinkContent);
    if (
      /^[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\x00-\x20\x7f]*$/.test(autolinkContent)
      || MARKDOWN_EMAIL_AUTOLINK_PATTERN.test(autolinkContent)
    ) {
      visible.push(autolinkContent);
      index = tagEnd + 1;
      continue;
    }
    if (invalidUriWhitespace) {
      visible.push(value.slice(index, tagEnd + 1));
      index = tagEnd + 1;
      continue;
    }

    if (!parseHtmlTag(value, index, tagEnd)) {
      visible.push(value.slice(index, tagEnd + 1));
    }
    index = tagEnd + 1;
  }

  return visible.join('');
}
function findRawHtmlTokenEndForCodeSpans(value: string, start: number): number {
  if (value[start] !== '<' || isEscapedMarkdownCharacter(value, start)) return -1;
  if (value.startsWith('<!--', start)) {
    const end = value.indexOf('-->', start + 4);
    return end >= 0 ? end + 2 : -1;
  }
  const rawEnd = findRawHtmlTokenEnd(value, start);
  if (rawEnd >= start) return rawEnd;
  const tagEnd = findHtmlTagEnd(value, start);
  return tagEnd >= 0 && parseHtmlTag(value, start, tagEnd) ? tagEnd : -1;
}

function stripMarkdownCodeSpans(value: string): string {
  const delimiter = String.fromCharCode(96);
  const runs: Array<{ start: number; end: number; length: number; escaped: boolean; hasClosing: boolean }> = [];
  let consecutiveBackslashes = 0;

  for (let index = 0; index < value.length; index += 1) {
    const rawHtmlEnd = value[index] === '<'
      ? findRawHtmlTokenEndForCodeSpans(value, index)
      : -1;
    if (rawHtmlEnd >= index) {
      consecutiveBackslashes = 0;
      index = rawHtmlEnd;
      continue;
    }
    if (value[index] !== delimiter) {
      consecutiveBackslashes = value[index] === '\\' ? consecutiveBackslashes + 1 : 0;
      continue;
    }

    const start = index;
    while (index < value.length && value[index] === delimiter) index += 1;
    runs.push({
      start,
      end: index,
      length: index - start,
      escaped: consecutiveBackslashes % 2 === 1,
      hasClosing: false,
    });
    consecutiveBackslashes = 0;
    index -= 1;
  }

  const futureRuns = new Map<number, number>();
  for (let index = runs.length - 1; index >= 0; index -= 1) {
    const run = runs[index];
    run.hasClosing = (futureRuns.get(run.length) || 0) > 0;
    futureRuns.set(run.length, (futureRuns.get(run.length) || 0) + 1);
  }

  const hiddenRanges: Array<[number, number]> = [];
  let activeStart = -1;
  let activeLength = 0;
  for (const run of runs) {
    if (activeLength > 0) {
      if (run.length === activeLength) {
        hiddenRanges.push([activeStart, run.end]);
        activeStart = -1;
        activeLength = 0;
      }
      continue;
    }
    if (!run.escaped && run.hasClosing) {
      activeStart = run.start;
      activeLength = run.length;
    }
  }

  let visible = '';
  let rangeIndex = 0;
  for (let index = 0; index < value.length; index += 1) {
    while (rangeIndex < hiddenRanges.length && index >= hiddenRanges[rangeIndex][1]) rangeIndex += 1;
    if (
      rangeIndex < hiddenRanges.length
      && index >= hiddenRanges[rangeIndex][0]
      && index < hiddenRanges[rangeIndex][1]
    ) {
      continue;
    }
    visible += value[index];
  }
  return visible;
}
function markdownIndentationColumns(value: string): number {
  let column = 0;
  for (const character of value) {
    if (character === ' ') {
      column += 1;
    } else if (character === '\t') {
      column += 4 - (column % 4);
    } else {
      break;
    }
  }
  return column;
}
function hasFourColumnIndentation(value: string): boolean {
  return markdownIndentationColumns(value) >= 4;
}
function stripMarkdownCode(value: string): string {
  let fenced = false;
  let fenceCharacter = '';
  let fenceLength = 0;
  let fenceContainerDepth: number | null = null;
  let fenceListDepth: number | null = null;
  let fenceListIndentation: number | null = null;
  let htmlBlockDepth = 0;
  let htmlBlockType1Tag = '';
  let htmlBlockComment = false;
  let directiveBlockDepth = 0;
  let htmlBlockEndSequence: '>' | '?>' | ']]>' | null = null;
  let paragraph = false;
  let paragraphBlockquoteDepth: number | null = null;
  let paragraphListDepth: number | null = null;
  let paragraphListIndentation: number | null = null;
  const lines = value.split(/\r?\n/);
  const visibleLines = lines.map((line, lineIndex) => {
    let content = line;
    let blockquoteDepth = 0;
    let listDepth = 0;
    let listItemIndentation = 0;
    let removedContainer = true;
    while (removedContainer) {
      removedContainer = false;
      const asciiReplyMarker = content.match(/^\s*>>\s*\d{1,7}\b/);
      const blockquote = content.match(/^\s{0,3}>[ \t]?/);
      if (asciiReplyMarker) break;
      if (blockquote) {
        blockquoteDepth += 1;
        content = content.slice(blockquote[0].length);
        removedContainer = true;
        continue;
      }
      const listItem = !fenced && content.match(/^(\s{0,3}(?:[-+*]|\d{1,9}[.)]))([ \t]+)/);
      if (listItem) {
        const padding = listItem[2];
        const consumedPadding = padding.length > 4 ? padding.slice(0, 1) : padding;
        const consumedLength = listItem[1].length + consumedPadding.length;
        listDepth += 1;
        listItemIndentation += consumedLength;
        content = content.slice(consumedLength);
        removedContainer = true;
        continue;
      }
    }

    let listContainerDepth = listDepth;
    const leadingIndentation = markdownIndentationColumns(content);
    if (
      paragraph
      && listDepth === 0
      && paragraphListDepth !== null
      && paragraphListIndentation !== null
      && leadingIndentation >= paragraphListIndentation
    ) {
      listDepth = paragraphListDepth;
      listContainerDepth = paragraphListDepth;
    }
    if (fenced && fenceListDepth !== null) {
      const leadingWhitespace = content.match(/^[ \t]*/)?.[0] || '';
      const indentation = leadingWhitespace.replace(/\t/g, '    ').length;
      const requiredIndentation = fenceListIndentation ?? fenceListDepth * 2;
      listContainerDepth = indentation >= requiredIndentation ? fenceListDepth : 0;
    }

    if (
      fenced
      && (
        fenceContainerDepth !== blockquoteDepth
        || fenceListDepth !== listContainerDepth
      )
    ) {
      fenced = false;
      fenceCharacter = '';
      fenceLength = 0;
      fenceContainerDepth = null;
      fenceListDepth = null;
      fenceListIndentation = null;
    }

    const isHtmlBlockLine = HTML_BLOCK_LINE_PATTERN.test(content);
    const htmlBlockTag = HTML_BLOCK_TAG_PATTERN.exec(content);
    if (!fenced && (htmlBlockDepth > 0 || htmlBlockType1Tag || htmlBlockComment || htmlBlockEndSequence !== null || isHtmlBlockLine)) {
      if (/^\s*$/.test(content)) {
        htmlBlockDepth = 0;
        htmlBlockType1Tag = '';
        htmlBlockComment = false;
        htmlBlockEndSequence = null;
      } else if (htmlBlockComment) {
        if (content.includes('-->')) {
          htmlBlockDepth = 0;
          htmlBlockComment = false;
        }
      } else if (htmlBlockEndSequence !== null) {
        if (content.includes(htmlBlockEndSequence)) {
          htmlBlockDepth = 0;
          htmlBlockEndSequence = null;
        }
      } else if (/^\s{0,3}<\?/.test(content)) {
        const processingStart = content.indexOf('<?');
        const processingEnd = content.indexOf('?>', processingStart + 2);
        htmlBlockEndSequence = processingEnd < 0 ? '?>' : null;
        htmlBlockDepth = htmlBlockEndSequence === null ? 0 : 1;
      } else if (/^\s{0,3}<!\[CDATA\[/.test(content)) {
        const cdataStart = content.indexOf('<![CDATA[');
        const cdataEnd = content.indexOf(']]>', cdataStart + 9);
        htmlBlockEndSequence = cdataEnd < 0 ? ']]>' : null;
        htmlBlockDepth = htmlBlockEndSequence === null ? 0 : 1;
      } else if (/^\s{0,3}<![A-Z]/.test(content)) {
        const declarationStart = content.indexOf('<!');
        const declarationEnd = content.indexOf('>', declarationStart + 2);
        htmlBlockEndSequence = declarationEnd < 0 ? '>' : null;
        htmlBlockDepth = htmlBlockEndSequence === null ? 0 : 1;
      } else if (
        htmlBlockType1Tag
        && new RegExp(
          '<\\s*/\\s*' + htmlBlockType1Tag + '\\s*>',
          'i',
        ).test(content)
      ) {
        htmlBlockDepth = 0;
        htmlBlockType1Tag = '';
      } else if (
        htmlBlockType1Tag
        && htmlBlockTag?.[1]
        && htmlBlockTag[2].toLowerCase() === htmlBlockType1Tag
      ) {
        htmlBlockDepth = 0;
        htmlBlockType1Tag = '';
      } else if (/^\s{0,3}<!--/.test(content)) {
        const commentStart = content.indexOf('<!--');
        const commentEnd = content.indexOf('-->', commentStart + 4);
        htmlBlockComment = commentEnd < 0;
        htmlBlockDepth = htmlBlockComment ? 1 : 0;
      } else if (htmlBlockTag && !htmlBlockTag[1] && !/\/\s*>$/.test(htmlBlockTag[0])) {
        const tagName = htmlBlockTag[2].toLowerCase();
        const hasInlineEndTag = new RegExp(
          '<\\s*/\\s*' + tagName + '\\s*>',
          'i',
        ).test(content.slice(htmlBlockTag[0].length));
        if (HTML_BLOCK_TYPE_1_TAGS.has(tagName) && !hasInlineEndTag) {
          htmlBlockType1Tag = tagName;
          htmlBlockDepth = 1;
        } else {
          htmlBlockDepth += 1;
        }
      }
      paragraph = false;
      return content;
    }

    const isDirectiveBlockLine = /^\s{0,3}:::(?:message|details)(?:\s|$)/i.test(content);
    const isDirectiveBlockCloser = /^\s{0,3}:::\s*$/.test(content);
    if (!fenced && isDirectiveBlockLine) {
      directiveBlockDepth += 1;
      paragraph = false;
      return content;
    }
    if (!fenced && directiveBlockDepth > 0 && isDirectiveBlockCloser) {
      directiveBlockDepth -= 1;
      paragraph = false;
      return content;
    }

    const fence = content.match(/^\s{0,3}(`{3,}|~{3,})([^\r\n]*)$/);
    if (fence) {
      const marker = fence[1];
      if (!fenced) {
        if (marker[0] === '`' && fence[2].includes('`')) return content;
        fenced = true;
        fenceCharacter = marker[0];
        fenceLength = marker.length;
        fenceContainerDepth = blockquoteDepth;
        fenceListDepth = listContainerDepth;
        fenceListIndentation = listItemIndentation;
      } else if (
        marker[0] === fenceCharacter
        && marker.length >= fenceLength
        && /^\s*$/.test(fence[2])
      ) {
        fenced = false;
        fenceContainerDepth = null;
        fenceListDepth = null;
        fenceListIndentation = null;
      }
      paragraph = false;
      return '';
    }
    if (fenced) return '';
    if (/^\s*$/.test(content)) {
      paragraph = false;
      return '';
    }
    if (
      paragraph
      && (
        paragraphBlockquoteDepth !== blockquoteDepth
        || paragraphListDepth !== listDepth
      )
    ) {
      paragraph = false;
    }
    if (hasFourColumnIndentation(content) && !paragraph) return '';
    const previousLine = lines[lineIndex - 1] || '';
    const isSetextUnderline =
      lineIndex > 0
      && isSetextHeadingText(previousLine)
      && /^\s{0,3}(?:=+|-+)\s*$/.test(content);
    const isTableDelimiterLine = isValidTableDelimiterLine(content, previousLine);
    const isGithubAlertLine = /^\s{0,3}\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i.test(content);

    const isReferenceDefinitionLine = isMarkdownReferenceDefinitionLine(content);
    const isBlockLine =
      /^\s{0,3}#{1,6}(?:[ \t]+|$)/.test(content)
      || THEMATIC_BREAK_LINE_PATTERN.test(content)
      || isSetextUnderline
      || isHtmlBlockLine
      || isTableDelimiterLine
      || isGithubAlertLine
      || isDirectiveBlockLine
      || isReferenceDefinitionLine;
    paragraph = !isBlockLine;
    paragraphBlockquoteDepth = blockquoteDepth;
    paragraphListDepth = listDepth;
    if (listDepth > 0) {
      paragraphListIndentation = listItemIndentation || paragraphListIndentation;
    } else {
      paragraphListIndentation = null;
    }
    return content;
  });

  // Remove inline code spans after joining lines so a valid multiline span
  // cannot leak a reply marker into the visible-text scan.
  const withoutCode = stripHiddenHtml(stripMarkdownCodeSpans(visibleLines.join('\n')));
  return stripHtmlTags(stripMarkdownLinkDestinations(withoutCode));
}
function decodeVisibleReplyMarkers(value: string): string {
  return value
    .replace(/\\>/g, '>')
    .replace(/&(?:gt|#0*62|#x0*3e|#0*65310|#x0*ff1e);/gi, '>')
    .replace(/&#(?:x[0-9a-f]+|[0-9]+);/gi, (entity) => {
      const hexadecimal = /^&#x/i.test(entity);
      const digits = entity.slice(hexadecimal ? 3 : 2, -1);
      const codePoint = Number.parseInt(digits, hexadecimal ? 16 : 10);
      const decoded = codePoint >= 0 && codePoint <= 0x10ffff
        ? String.fromCodePoint(codePoint)
        : entity;
      return (codePoint >= 0x30 && codePoint <= 0x39) || /^
\
s$/u.test(decoded)
        ? decoded
        : entity;
    });
}

function countMarkdownTableCells(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed.includes('|')) return undefined;
  const start = trimmed.startsWith('|') ? 1 : 0;
  const end = trimmed.endsWith('|') ? trimmed.length - 1 : trimmed.length;
  let count = 1;
  let escaped = false;
  for (let index = start; index < end; index += 1) {
    if (escaped) {
      escaped = false;
    } else if (trimmed[index] === '\\') {
      escaped = true;
    } else if (trimmed[index] === '|') {
      count += 1;
    }
  }
  return count;
}

function isSetextHeadingText(value: string): boolean {
  const normalized = value.replace(/^\s{0,3}(?:>\s?)+/, '');
  if (!normalized.trim()) return false;
  return !(
    /^\s{0,3}#{1,6}(?:[ \t]+|$)/.test(normalized)
    || /^\s{0,3}(?:\x60{3,}|~{3,})/.test(normalized)
    || THEMATIC_BREAK_LINE_PATTERN.test(normalized)
    || /^\s{0,3}\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i.test(normalized)
    || /^\s{0,3}:::(?:message|details)(?:\s|$)/i.test(normalized)
    || /^\s{0,3}:::\s*$/.test(normalized)
    || isMarkdownReferenceDefinitionLine(normalized)
    || HTML_BLOCK_LINE_PATTERN.test(normalized)
    || /^\s{0,3}(?:[-+*]|1[.)])[ \t]+/.test(normalized)
  );
}

function isValidTableDelimiterLine(value: string, previousLine: string): boolean {
  if (!/^\s{0,3}\|?(?:\s*:?-+:?\s*\|)+\s*$/.test(value)) return false;
  if (!isSetextHeadingText(previousLine)) return false;
  const headerCells = countMarkdownTableCells(previousLine);
  const delimiterCells = countMarkdownTableCells(value);
  return headerCells !== undefined && headerCells === delimiterCells;
}

function parseReplyNumbers(
  value: unknown,
  bodyMarkdown: string,
  budget: ReplyTargetBudget,
): number[] {
  if (budget.used >= budget.limit) return [];
  const replies = new Set<number>();
  const addReply = (number: number | undefined): boolean => {
    if (number === undefined || replies.has(number)) return true;
    if (budget.used >= budget.limit) return false;
    replies.add(number);
    budget.used += 1;
    return true;
  };
  for (const item of list(value, MAX_THREAD_REPLIES)) {
    const number = positiveInteger(item);
    if (!addReply(number)) return [...replies];
    if (replies.size >= MAX_THREAD_REPLIES || budget.used >= budget.limit) return [...replies];
  }

  const visibleBody = decodeVisibleReplyMarkers(stripMarkdownCode(bodyMarkdown));
  for (const match of visibleBody.matchAll(/(?:>>|＞＞)\s*(\d{1,7})\b/g)) {
    const number = positiveInteger(match[1]);
    if (!addReply(number)) return [...replies];
    if (replies.size >= MAX_THREAD_REPLIES || budget.used >= budget.limit) break;
  }
  return [...replies];
}

function normalizeSource(value: unknown): KnowledgeThreadSource | undefined {
  if (typeof value === 'string') {
    const url = boundedStringValue(value);
    return url && safeKnowledgeHref(url) ? { label: url, url } : undefined;
  }
  const source = record(value);
  if (!source) return undefined;
  const url = boundedStringValue(source.url ?? source.href);
  if (!url || !safeKnowledgeHref(url)) return undefined;
  return {
    label: boundedStringValue(source.label ?? source.title ?? source.name) || url,
    url,
  };
}

function normalizeSources(value: unknown, budget: ByteBudget): KnowledgeThreadSource[] {
  if (!Array.isArray(value)) return [];
  const sources: KnowledgeThreadSource[] = [];
  for (const item of value.slice(0, MAX_THREAD_SOURCES)) {
    const source = normalizeSource(item);
    if (!source) continue;
    const sourceBytes = utf8ByteLength(source.label) + utf8ByteLength(source.url);
    if (budget.used + sourceBytes > budget.limit) {
      if (budget.used >= budget.limit) break;
      continue;
    }
    budget.used += sourceBytes;
    sources.push(source);
  }
  return sources;
}

export function safeKnowledgeHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? value : null;
  } catch {
    return null;
  }
}

export function isThreadKnowledge(frontmatter: Frontmatter): boolean {
  const format = boundedStringValue(frontmatter.format ?? frontmatter.knowledge_format)?.toLowerCase();
  if (format === 'thread') return true;
  return Array.isArray(frontmatter.thread_posts)
    || Array.isArray(record(frontmatter.thread)?.posts);
}

export function parseKnowledgeThread(frontmatter: Frontmatter): KnowledgeThread | null {
  const metadata = record(frontmatter.thread);
  if (!isThreadKnowledge(frontmatter)) return null;

  const rawPosts = threadPostsValue(frontmatter, metadata);
  const nextFreeNumbers = new Map<number, number>();
  const findNextFreeNumber = (start: number): number => {
    let candidate = Math.max(1, Math.min(start, MAX_POST_NUMBER + 1));
    const traversed: number[] = [];
    while (nextFreeNumbers.has(candidate)) {
      traversed.push(candidate);
      candidate = nextFreeNumbers.get(candidate) as number;
    }
    for (const traversedNumber of traversed) nextFreeNumbers.set(traversedNumber, candidate);
    return candidate;
  };
  const allocatePostNumber = (requested: number): number => {
    let number = findNextFreeNumber(requested);
    if (number > MAX_POST_NUMBER) number = findNextFreeNumber(1);
    if (number > MAX_POST_NUMBER) return MAX_POST_NUMBER;
    nextFreeNumbers.set(number, findNextFreeNumber(number + 1));
    return number;
  };
  const rawPostValues = Array.isArray(rawPosts) ? rawPosts.slice(0, MAX_THREAD_POSTS) : [];
  const posts: KnowledgeThreadPost[] = [];
  let aggregateBodyBytes = 0;
  let aggregateMetadataBytes = 0;
  const replyTargetBudget: ReplyTargetBudget = { used: 0, limit: MAX_THREAD_REPLY_TARGETS };
  for (const [index, value] of rawPostValues.entries()) {
    const source = record(value);
    const rawBodyMarkdown = typeof value === 'string'
      ? value
      : rawMarkdownBodyValue(source?.body ?? source?.content ?? source?.markdown);
    const bodyMarkdown = trimSurroundingBlankLines(
      truncateUtf8(rawBodyMarkdown, MAX_THREAD_POST_BODY_BYTES),
    );
    const bodyBytes = utf8ByteLength(bodyMarkdown);
    if (aggregateBodyBytes + bodyBytes > MAX_THREAD_BODY_BYTES) break;
    const name = boundedStringValue(source?.name ?? source?.author ?? source?.display_name) || '名無しさん';
    const role = boundedStringValue(source?.role);
    const id = boundedStringValue(source?.id ?? source?.user_id);
    const postedAt = boundedStringValue(source?.posted_at ?? source?.postedAt ?? source?.date);
    const metadataBytes = [name, role, id, postedAt]
      .reduce((total, field) => total + utf8ByteLength(field || ''), 0);
    if (aggregateMetadataBytes + metadataBytes > MAX_THREAD_POST_METADATA_BYTES) break;
    aggregateBodyBytes += bodyBytes;
    aggregateMetadataBytes += metadataBytes;
    const requestedNumber = positiveInteger(source?.number ?? source?.no ?? source?.index) || index + 1;
    const number = allocatePostNumber(requestedNumber);
    posts.push({
      number,
      name,
      role,
      id,
      postedAt,
      bodyMarkdown,
      replyTo: parseReplyNumbers(
        source?.reply_to ?? source?.replyTo ?? source?.references,
        bodyMarkdown,
        replyTargetBudget,
      ),
    });
  }

  const metadataBudget: ByteBudget = { used: 0, limit: MAX_THREAD_METADATA_BYTES };
  const sourceValues = metadata?.sources ?? frontmatter.sources ?? frontmatter.references;
  const part = takeMetadataString(metadata?.part ?? frontmatter.thread_part ?? frontmatter.part, metadataBudget);
  const theme = takeMetadataString(metadata?.theme ?? frontmatter.thread_theme ?? frontmatter.theme, metadataBudget);
  const rules = normalizeMetadataList(
    metadata?.rules ?? frontmatter.thread_rules ?? frontmatter.rules,
    MAX_THREAD_RULES,
    metadataBudget,
  );
  const sources = normalizeSources(sourceValues, metadataBudget);
  return {
    metadata: {
      part,
      theme,
      rules,
      sources,
    },
    posts,
  };
}
