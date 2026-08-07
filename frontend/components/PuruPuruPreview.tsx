'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import HfIcon from './HfIcon';

const FRAME_BLEND_MS = 180;

export interface PuruPuruPreviewFrame {
  src: string;
  direction: string;
  state: string;
}

function directionLabel(direction: string, locale: 'ja' | 'en') {
  const labels: Record<string, [string, string]> = {
    front: ['正面', 'Front'],
    left: ['左', 'Left'],
    right: ['右', 'Right'],
    up: ['上', 'Up'],
    down: ['下', 'Down'],
  };
  const label = labels[direction] || [direction, direction];
  return locale === 'ja' ? label[0] : label[1];
}

function stateLabel(state: string, locale: 'ja' | 'en') {
  const eyes = state.includes('eyes-closed')
    ? (locale === 'ja' ? '目閉じ' : 'Eyes closed')
    : (locale === 'ja' ? '目開き' : 'Eyes open');
  const mouth = state.includes('mouth-open')
    ? (locale === 'ja' ? '口開き' : 'Mouth open')
    : state.includes('mouth-half')
      ? (locale === 'ja' ? '発話中' : 'Talking')
      : (locale === 'ja' ? '口閉じ' : 'Mouth closed');
  return `${eyes} · ${mouth}`;
}

export default function PuruPuruPreview({
  frames,
  locale,
  compact = false,
}: {
  frames: PuruPuruPreviewFrame[];
  locale: 'ja' | 'en';
  compact?: boolean;
}) {
  const directions = useMemo(() => Array.from(new Set(frames.map((frame) => frame.direction))), [frames]);
  const [direction, setDirection] = useState(directions[0] || 'front');
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [framesReady, setFramesReady] = useState(false);
  const [previousFrame, setPreviousFrame] = useState<PuruPuruPreviewFrame | null>(null);
  const preloadedImagesRef = useRef<HTMLImageElement[]>([]);
  const sequence = compact ? frames : frames.filter((frame) => frame.direction === direction);
  const activeFrame = sequence[frameIndex % Math.max(sequence.length, 1)] || frames[0];
  const activeFrameRef = useRef(activeFrame);

  useEffect(() => {
    activeFrameRef.current = activeFrame;
  }, [activeFrame]);

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (reducedMotion.matches) setPlaying(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setFramesReady(false);
    const images = frames.map((frame) => {
      const image = new Image();
      image.src = frame.src;
      return image;
    });
    preloadedImagesRef.current = images;
    Promise.all(images.map(async (image) => {
      if (image.complete && image.naturalWidth > 0) return;
      try {
        await image.decode();
      } catch {
        if (image.complete) return;
        await new Promise<void>((resolve) => {
          image.addEventListener('load', () => resolve(), { once: true });
          image.addEventListener('error', () => resolve(), { once: true });
        });
      }
    })).then(() => {
      if (!cancelled) setFramesReady(true);
    });
    return () => {
      cancelled = true;
      preloadedImagesRef.current = [];
    };
  }, [frames]);

  useEffect(() => {
    if (!playing || !framesReady || sequence.length < 2) return undefined;
    const timer = window.setInterval(() => {
      setPreviousFrame(activeFrameRef.current || null);
      setFrameIndex((current) => (current + 1) % sequence.length);
    }, compact ? 640 : 520);
    return () => window.clearInterval(timer);
  }, [compact, framesReady, playing, sequence.length]);

  useEffect(() => {
    if (!previousFrame) return undefined;
    const timer = window.setTimeout(() => setPreviousFrame(null), FRAME_BLEND_MS + 20);
    return () => window.clearTimeout(timer);
  }, [activeFrame?.src, previousFrame]);

  if (!activeFrame) return null;

  const changeDirection = (nextDirection: string) => {
    if (nextDirection === direction) return;
    setPreviousFrame(activeFrameRef.current || null);
    setDirection(nextDirection);
    setFrameIndex(0);
  };

  return (
    <div
      className={`nyankoface-purupuru-preview relative isolate overflow-hidden ${compact ? 'h-full w-full' : 'min-h-72 w-full'}`}
      data-purupuru-preview
      data-frame-path={activeFrame.src}
      data-frame-index={frameIndex}
      data-direction={activeFrame.direction}
      data-transition-ms={FRAME_BLEND_MS}
      data-frames-ready={framesReady ? 'true' : 'false'}
      data-blend-active={previousFrame ? 'true' : 'false'}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(103,232,249,.18),transparent_44%),linear-gradient(145deg,#09090b,#111827)]" />
      <div className="absolute inset-0 opacity-20 [background-image:linear-gradient(rgba(255,255,255,.12)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.12)_1px,transparent_1px)] [background-size:24px_24px]" />
      {previousFrame ? (
        <img
          key={`previous-${previousFrame.src}`}
          src={previousFrame.src}
          alt=""
          aria-hidden="true"
          data-purupuru-layer="previous"
          className={`nyankoface-purupuru-frame nyankoface-purupuru-frame-previous absolute inset-0 z-10 h-full w-full object-contain ${compact ? 'p-3' : 'max-h-[440px] min-h-72 p-5'}`}
        />
      ) : null}
      <img
        key={activeFrame.src}
        src={activeFrame.src}
        alt={`${directionLabel(activeFrame.direction, locale)} ${stateLabel(activeFrame.state, locale)} PuruPuru animated preview`}
        data-purupuru-layer="current"
        className={`nyankoface-purupuru-frame nyankoface-purupuru-frame-current relative z-10 h-full w-full object-contain ${previousFrame ? 'nyankoface-purupuru-frame-incoming' : ''} ${compact ? 'p-3' : 'max-h-[440px] min-h-72 p-5'}`}
      />
      <div className={`absolute z-20 flex items-center gap-2 rounded-full border border-white/15 bg-black/65 font-mono text-[10px] font-bold uppercase tracking-wider text-cyan-100 backdrop-blur ${compact ? 'bottom-3 left-3 px-2.5 py-1' : 'bottom-4 left-4 px-3 py-1.5'}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${playing ? 'animate-pulse bg-emerald-300' : 'bg-zinc-400'}`} />
        {directionLabel(activeFrame.direction, locale)} · {stateLabel(activeFrame.state, locale)}
      </div>
      {!compact ? (
        <div className="absolute bottom-4 right-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap justify-end gap-1.5">
          {directions.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => changeDirection(item)}
              data-purupuru-direction={item}
              className={`rounded-full border px-2.5 py-1 text-xs font-semibold backdrop-blur transition ${item === direction ? 'nyankoface-character-selection-active border-cyan-200 bg-cyan-200' : 'border-white/20 bg-black/55 text-white hover:border-cyan-200'}`}
              aria-pressed={item === direction}
            >
              {directionLabel(item, locale)}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPlaying((current) => !current)}
            data-purupuru-toggle
            className="grid h-7 w-7 place-items-center rounded-full border border-white/20 bg-black/55 text-white backdrop-blur transition hover:border-cyan-200"
            aria-label={playing ? (locale === 'ja' ? 'アニメーションを停止' : 'Pause animation') : (locale === 'ja' ? 'アニメーションを再生' : 'Play animation')}
          >
            <HfIcon name={playing ? 'pause' : 'play'} className="h-2.5 w-2.5" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
