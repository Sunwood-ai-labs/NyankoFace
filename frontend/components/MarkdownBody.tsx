'use client';

import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from 'react';

type MarkdownBodyProps = {
  html: string;
  className: string;
};

type NyankoFaceTheme = 'standard' | 'solarpunk' | 'cyberpunk';

function currentTheme(): NyankoFaceTheme {
  const explicit = document.documentElement.dataset.nyankofaceTheme;
  if (explicit === 'solarpunk' || explicit === 'cyberpunk') return explicit;
  return 'standard';
}

function mermaidTheme(theme: NyankoFaceTheme, darkMode: boolean) {
  if (theme === 'solarpunk') {
    return {
      darkMode: false,
      background: '#f8fbf1',
      primaryColor: '#dfead8',
      primaryTextColor: '#173b2c',
      primaryBorderColor: '#62a370',
      lineColor: '#1e633d',
      secondaryColor: '#f4d9a0',
      tertiaryColor: '#e0d6f5',
      edgeLabelBackground: '#f8fbf1',
      clusterBkg: '#edf3e7',
      clusterBorder: '#94b889',
      noteBkgColor: '#fff8d8',
      noteTextColor: '#173b2c',
      noteBorderColor: '#bc8b36',
    };
  }

  if (theme === 'cyberpunk' || darkMode) {
    return {
      darkMode: true,
      background: '#050814',
      primaryColor: '#111a33',
      primaryTextColor: '#e9f8ff',
      primaryBorderColor: '#69e9ff',
      lineColor: '#69e9ff',
      secondaryColor: '#261236',
      tertiaryColor: '#162641',
      edgeLabelBackground: '#0a0d1d',
      clusterBkg: '#0d1327',
      clusterBorder: '#31536b',
      noteBkgColor: '#241632',
      noteTextColor: '#f2fbff',
      noteBorderColor: '#ff5caf',
    };
  }

  return {
    darkMode: false,
    background: '#ffffff',
    primaryColor: '#f6f8fa',
    primaryTextColor: '#1f2328',
    primaryBorderColor: '#8c959f',
    lineColor: '#57606a',
    secondaryColor: '#ddf4ff',
    tertiaryColor: '#fff8c5',
    edgeLabelBackground: '#ffffff',
    clusterBkg: '#f6f8fa',
    clusterBorder: '#d1d9e0',
    noteBkgColor: '#fff8c5',
    noteTextColor: '#1f2328',
    noteBorderColor: '#d4a72c',
  };
}

const MarkdownBodyThemeContext = createContext<number | undefined>(undefined);

export function MarkdownBodyThemeProvider({ children }: { children: ReactNode }) {
  const [themeRevision, setThemeRevision] = useState(0);

  useEffect(() => {
    const root = document.documentElement;
    const colorScheme = window.matchMedia('(prefers-color-scheme: dark)');
    const rerender = () => setThemeRevision((revision) => revision + 1);
    const observer = new MutationObserver(rerender);
    observer.observe(root, { attributes: true, attributeFilter: ['data-nyankoface-theme'] });
    colorScheme.addEventListener('change', rerender);
    return () => {
      observer.disconnect();
      colorScheme.removeEventListener('change', rerender);
    };
  }, []);

  return (
    <MarkdownBodyThemeContext.Provider value={themeRevision}>
      {children}
    </MarkdownBodyThemeContext.Provider>
  );
}
export default function MarkdownBody({ html, className }: MarkdownBodyProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const sharedThemeRevision = useContext(MarkdownBodyThemeContext);
  const [localThemeRevision, setLocalThemeRevision] = useState(0);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const timers = new Set<number>();
    const copyText = async (text: string) => {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.append(textarea);
      textarea.select();
      const copied = document.execCommand('copy');
      textarea.remove();
      if (!copied) throw new Error('Copy command failed');
    };
    const handleCopy = async (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const button = target.closest<HTMLButtonElement>('[data-nyankoface-copy-code]');
      if (!button || !root.contains(button)) return;
      const figure = button.closest<HTMLElement>('.nyankoface-code-block');
      const code = figure?.querySelector('code');
      const status = figure?.querySelector<HTMLElement>('[data-nyankoface-copy-status]');
      if (!code || !status) return;
      const japanese = document.documentElement.lang === 'ja';
      button.disabled = true;
      try {
        await copyText(code.textContent || '');
        button.dataset.copyState = 'success';
        button.textContent = japanese ? 'コピー済み' : 'Copied';
        status.textContent = japanese ? 'コードをクリップボードにコピーしました。' : 'Code copied to clipboard.';
      } catch {
        button.dataset.copyState = 'error';
        button.textContent = japanese ? '失敗' : 'Failed';
        status.textContent = japanese ? 'コードをコピーできませんでした。' : 'Code could not be copied.';
      }
      const timer = window.setTimeout(() => {
        button.disabled = false;
        delete button.dataset.copyState;
        button.textContent = japanese ? 'コピー' : 'Copy';
        status.textContent = '';
        timers.delete(timer);
      }, 1800);
      timers.add(timer);
    };
    root.dataset.codeControls = 'ready';
    root.addEventListener('click', handleCopy);
    return () => {
      root.removeEventListener('click', handleCopy);
      delete root.dataset.codeControls;
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [html]);

  useEffect(() => {
    if (sharedThemeRevision !== undefined) return;
    const root = document.documentElement;
    const colorScheme = window.matchMedia('(prefers-color-scheme: dark)');
    const rerender = () => setLocalThemeRevision((revision) => revision + 1);
    const observer = new MutationObserver(rerender);
    observer.observe(root, { attributes: true, attributeFilter: ['data-nyankoface-theme'] });
    colorScheme.addEventListener('change', rerender);
    return () => {
      observer.disconnect();
      colorScheme.removeEventListener('change', rerender);
    };
  }, [sharedThemeRevision]);

  const themeRevision = sharedThemeRevision ?? localThemeRevision;

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const codeBlocks = Array.from(root.querySelectorAll<HTMLElement>('pre > code.language-mermaid'));
    if (codeBlocks.length === 0) return;

    let cancelled = false;
    const render = async () => {
      const { default: mermaid } = await import('mermaid');
      if (cancelled) return;
      const theme = currentTheme();
      const darkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const uiFontFamily =
        window.getComputedStyle(document.documentElement).getPropertyValue('--nyankoface-ui-font').trim() ||
        '"Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic UI", "Noto Sans JP", sans-serif';
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        themeVariables: mermaidTheme(theme, darkMode),
        fontFamily: uiFontFamily,
        flowchart: { htmlLabels: false, useMaxWidth: true },
        sequence: { useMaxWidth: true, wrap: true },
      });

      for (const [index, codeBlock] of codeBlocks.entries()) {
        if (cancelled) return;
        const source = codeBlock.textContent?.trim() || '';
        const pre = codeBlock.parentElement;
        if (!pre || !source) continue;
        const figure = document.createElement('figure');
        figure.className = 'nyankoface-mermaid';
        figure.dataset.mermaidState = 'loading';
        figure.setAttribute('aria-label', 'Mermaid diagram');
        const viewport = document.createElement('div');
        viewport.className = 'nyankoface-mermaid-viewport';
        figure.append(viewport);
        pre.replaceWith(figure);

        try {
          const parsed = await mermaid.parse(source, { suppressErrors: true });
          if (!parsed) throw new Error('Invalid Mermaid syntax');
          const id = `nyankoface-mermaid-${themeRevision}-${index}-${Math.random().toString(36).slice(2)}`;
          const { svg, bindFunctions } = await mermaid.render(id, source);
          if (cancelled) return;
          viewport.innerHTML = svg;
          bindFunctions?.(viewport);
          figure.dataset.mermaidView = 'fit';
          const controls = document.createElement('figcaption');
          controls.className = 'nyankoface-mermaid-controls';
          const controlLabel = document.createElement('span');
          controlLabel.textContent = 'Mermaid';
          const zoomButton = document.createElement('button');
          zoomButton.type = 'button';
          zoomButton.className = 'nyankoface-mermaid-zoom';
          const japanese = document.documentElement.lang === 'ja';
          const updateZoomLabel = () => {
            const actualSize = figure.dataset.mermaidView === 'actual';
            zoomButton.textContent = actualSize
              ? (japanese ? '全体表示' : 'Fit diagram')
              : (japanese ? '拡大' : 'Zoom');
            zoomButton.setAttribute('aria-pressed', String(actualSize));
          };
          zoomButton.addEventListener('click', () => {
            const actualSize = figure.dataset.mermaidView === 'actual';
            figure.dataset.mermaidView = actualSize ? 'fit' : 'actual';
            viewport.scrollLeft = 0;
            updateZoomLabel();
          });
          updateZoomLabel();
          controls.append(controlLabel, zoomButton);
          figure.prepend(controls);
          figure.dataset.mermaidState = 'rendered';
        } catch {
          viewport.textContent = source;
          viewport.classList.add('nyankoface-mermaid-fallback');
          const message = document.createElement('figcaption');
          message.className = 'nyankoface-mermaid-error';
          message.textContent = document.documentElement.lang === 'ja'
            ? 'Mermaid図を描画できませんでした。代わりにソースを表示しています。'
            : 'Mermaid diagram could not be rendered. Showing the source instead.';
          figure.append(message);
          figure.dataset.mermaidState = 'error';
        }
      }
    };

    void render();
    return () => {
      cancelled = true;
    };
  }, [html, themeRevision]);

  return <div ref={rootRef} className={className} data-nyankoface-markdown dangerouslySetInnerHTML={{ __html: html }} />;
}
