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

function stringValue(value: unknown): string | undefined {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString();
  }
  if (typeof value !== 'string' && typeof value !== 'number') return undefined;
  const normalized = String(value).trim();
  return normalized || undefined;
}

function trimSurroundingBlankLines(value: string): string {
  if (!value.trim()) return '';
  return value
    .replace(/^(?:[ \t]*\r?\n)+/, '')
    .replace(/(?:\r?\n[ \t]*)+$/, '');
}

function markdownBodyValue(value: unknown): string {
  if (typeof value === 'string') return trimSurroundingBlankLines(value);
  if (typeof value === 'number') return trimSurroundingBlankLines(String(value));
  return '';
}
function list(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(stringValue).filter((item): item is string => Boolean(item));
  }
  const single = stringValue(value);
  return single ? single.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean) : [];
}

const MAX_POST_NUMBER = 1_000_000;
const MAX_THREAD_POSTS = 2_048;
const MAX_THREAD_RULES = 256;
const MAX_THREAD_SOURCES = 256;
function positiveInteger(value: unknown): number | undefined {
  const number = typeof value === 'number'
    ? value
    : typeof value === 'string' && /^[+]?\d+$/.test(value.trim())
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

const HTML_BLOCK_LINE_PATTERN = /^\s{0,3}(?:<!--|<\?|<!\[CDATA\[|<\/?(?:address|article|aside|blockquote|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|nav|ol|p|pre|script|section|style|summary|table|tbody|td|tfoot|th|thead|title|tr|ul)(?:\s|\/?>))/i;
const HTML_BLOCK_TAG_PATTERN = /^\s{0,3}<\s*(\/?)\s*(address|article|aside|blockquote|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|nav|ol|p|pre|script|section|style|summary|table|tbody|td|tfoot|th|thead|title|tr|ul)\b[^>]*>/i;

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
    while (index < value.length && !/[\s\x00-\x1f]/.test(value[index])) index += 1;
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

function stripMarkdownLinkDestinations(value: string): string {
  let visible = '';
  const bracketEnds = findMarkdownDelimiterEnds(value, '[', ']');
  const parenthesisEnds = findMarkdownLinkDelimiterEnds(value);
  const referenceDefinitionPattern = /^[ \t]{0,3}\[((?:\\.|[^\[\]\\])+)\]:[ \t]*(?:\r?\n[ \t]+)?(?:<[^>\r\n]+>|(?:[^\s\r\n()]|\([^()\r\n]*\))+)(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?(?:\r?\n[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?[ \t]*$/gm;
  const referenceDefinitions = new Set(
    [...value.matchAll(referenceDefinitionPattern)]
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
        if (
          destinationEnd >= 0
          && isValidInlineLinkContent(value.slice(labelEnd + 2, destinationEnd))
        ) {
          if (!isImage) visible += value.slice(index, labelEnd + 1);
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
        if (!isImage) visible += value.slice(index, labelEnd + 1);
        index = referenceEnd >= 0 ? referenceEnd + 1 : labelEnd + 1;
        continue;
      }
    }
    visible += value[index];
    index += 1;
  }
  return visible.replace(/^[ \t]{0,3}\[(?:\\.|[^\[\]\\])+\]:[ \t]*(?:\r?\n[ \t]+)?(?:<[^>\r\n]+>|(?:[^\s\r\n()]|\([^()\r\n]*\))+)(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?(?:\r?\n[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^)]*\)))?[ \t]*$/gm, '');
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

    if (!parseHtmlTag(value, index, tagEnd)) {
      visible.push(value.slice(index, tagEnd + 1));
    }
    index = tagEnd + 1;
  }

  return visible.join('');
}
function stripMarkdownCodeSpans(value: string): string {
  const delimiter = String.fromCharCode(96);
  const runs: Array<{ start: number; end: number; length: number; escaped: boolean; hasClosing: boolean }> = [];
  let consecutiveBackslashes = 0;

  for (let index = 0; index < value.length; index += 1) {
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
function stripMarkdownCode(value: string): string {
  let fenced = false;
  let fenceCharacter = '';
  let fenceLength = 0;
  let fenceContainerDepth: number | null = null;
  let fenceListDepth: number | null = null;
  let fenceListIndentation: number | null = null;
  let htmlBlockDepth = 0;
  let paragraph = false;
  let paragraphBlockquoteDepth: number | null = null;
  let paragraphListDepth: number | null = null;
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
    if (!fenced && (htmlBlockDepth > 0 || isHtmlBlockLine)) {
      if (/^\s*$/.test(content)) {
        htmlBlockDepth = 0;
      } else if (htmlBlockTag && !htmlBlockTag[1] && !/\/\s*>$/.test(htmlBlockTag[0])) {
        htmlBlockDepth += 1;
      }
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
    if (/^(?: {4,}|\t)/.test(content) && !paragraph) return '';
    const previousLine = lines[lineIndex - 1] || '';
    const isSetextUnderline =
      lineIndex > 0
      && !/^\s*$/.test(previousLine)
      && /^\s{0,3}=+\s*$/.test(content);
    const isTableDelimiterLine = /^\s{0,3}\|?(?:\s*:?-+:?\s*\|)+\s*$/.test(content);
    const isDirectiveBlockLine = /^\s{0,3}:::(?:message|details)(?:\s|$)/i.test(content);
    const isBlockLine =
      /^\s{0,3}#{1,6}(?:[ \t]+|$)/.test(content)
      || /^\s{0,3}(?:(?:\*[\t ]*){3,}|(?:-[\t ]*){3,}|(?:_[\t ]*){3,})$/.test(content)
      || isSetextUnderline
      || isHtmlBlockLine
      || isTableDelimiterLine
      || isDirectiveBlockLine;
    paragraph = !isBlockLine;
    paragraphBlockquoteDepth = blockquoteDepth;
    paragraphListDepth = listDepth;
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
    .replace(/&(?:gt|#0*62|#x0*3e|#0*65310|#x0*ff1e);/gi, '>');
}

function parseReplyNumbers(value: unknown, bodyMarkdown: string): number[] {
  const explicit = list(value)
    .map((item) => positiveInteger(item))
    .filter((item): item is number => item !== undefined);
  const anchors = [...decodeVisibleReplyMarkers(stripMarkdownCode(bodyMarkdown)).matchAll(/(?:>>|＞＞)\s*(\d{1,7})\b/g)]
    .map((match) => positiveInteger(match[1]))
    .filter((item): item is number => item !== undefined);
  return [...new Set([...explicit, ...anchors])];
}

function normalizeSource(value: unknown): KnowledgeThreadSource | undefined {
  if (typeof value === 'string') {
    const url = value.trim();
    return url && safeKnowledgeHref(url) ? { label: url, url } : undefined;
  }
  const source = record(value);
  if (!source) return undefined;
  const url = stringValue(source.url ?? source.href);
  if (!url || !safeKnowledgeHref(url)) return undefined;
  return {
    label: stringValue(source.label ?? source.title ?? source.name) || url,
    url,
  };
}

function normalizeSources(value: unknown): KnowledgeThreadSource[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_THREAD_SOURCES).map(normalizeSource).filter((item): item is KnowledgeThreadSource => Boolean(item));
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
  const format = stringValue(frontmatter.format ?? frontmatter.knowledge_format)?.toLowerCase();
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
  const posts = rawPostValues.map((value, index) => {
    const source = record(value);
    const bodyMarkdown = typeof value === 'string'
      ? trimSurroundingBlankLines(value)
      : markdownBodyValue(source?.body ?? source?.content ?? source?.markdown);
    const requestedNumber = positiveInteger(source?.number ?? source?.no ?? source?.index) || index + 1;
    return {
      source,
      bodyMarkdown,
      requestedNumber,
    };
  }).reduce<KnowledgeThreadPost[]>((normalized, item) => {
    const number = allocatePostNumber(item.requestedNumber);
    normalized.push({
      number,
      name: stringValue(item.source?.name ?? item.source?.author ?? item.source?.display_name) || '名無しさん',
      role: stringValue(item.source?.role),
      id: stringValue(item.source?.id ?? item.source?.user_id),
      postedAt: stringValue(item.source?.posted_at ?? item.source?.postedAt ?? item.source?.date),
      bodyMarkdown: item.bodyMarkdown,
      replyTo: parseReplyNumbers(item.source?.reply_to ?? item.source?.replyTo ?? item.source?.references, item.bodyMarkdown),
    });
    return normalized;
  }, []);

  const sourceValues = metadata?.sources ?? frontmatter.sources ?? frontmatter.references;
  return {
    metadata: {
      part: stringValue(metadata?.part ?? frontmatter.thread_part ?? frontmatter.part),
      theme: stringValue(metadata?.theme ?? frontmatter.thread_theme ?? frontmatter.theme),
      rules: list(metadata?.rules ?? frontmatter.thread_rules ?? frontmatter.rules).slice(0, MAX_THREAD_RULES),
      sources: normalizeSources(sourceValues),
    },
    posts,
  };
}
