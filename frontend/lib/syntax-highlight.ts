import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import ini from 'highlight.js/lib/languages/ini';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import plaintext from 'highlight.js/lib/languages/plaintext';
import powershell from 'highlight.js/lib/languages/powershell';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';

const languages = {
  bash,
  css,
  diff,
  dockerfile,
  ini,
  javascript,
  json,
  markdown,
  plaintext,
  powershell,
  python,
  sql,
  typescript,
  xml,
  yaml,
} as const;

for (const [name, grammar] of Object.entries(languages)) {
  hljs.registerLanguage(name, grammar);
}

const aliases: Record<string, keyof typeof languages> = {
  bash: 'bash',
  css: 'css',
  diff: 'diff',
  docker: 'dockerfile',
  dockerfile: 'dockerfile',
  htm: 'xml',
  html: 'xml',
  ini: 'ini',
  js: 'javascript',
  javascript: 'javascript',
  json: 'json',
  jsx: 'javascript',
  md: 'markdown',
  markdown: 'markdown',
  plaintext: 'plaintext',
  ps1: 'powershell',
  powershell: 'powershell',
  py: 'python',
  python: 'python',
  sh: 'bash',
  shell: 'bash',
  sql: 'sql',
  text: 'plaintext',
  toml: 'ini',
  ts: 'typescript',
  tsx: 'typescript',
  typescript: 'typescript',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
};

export interface HighlightedCode {
  html: string;
  language: string;
  knownLanguage: boolean;
}

export function normalizeCodeLanguage(language: string | undefined): string {
  return language?.trim().toLocaleLowerCase().replace(/^language-/, '') || 'text';
}

export function highlightCode(source: string, requestedLanguage?: string): HighlightedCode {
  const language = normalizeCodeLanguage(requestedLanguage);
  const grammar = aliases[language];
  if (!grammar || grammar === 'plaintext') {
    return {
      html: hljs.highlight(source, { language: 'plaintext', ignoreIllegals: true }).value,
      language,
      knownLanguage: Boolean(grammar),
    };
  }
  return {
    html: hljs.highlight(source, { language: grammar, ignoreIllegals: true }).value,
    language,
    knownLanguage: true,
  };
}
