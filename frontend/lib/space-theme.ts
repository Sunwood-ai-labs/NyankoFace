export const SPACE_THEMES = [
  { gradient: 'from-violet-700 via-purple-700 to-fuchsia-700', glow: 'bg-fuchsia-200' },
  { gradient: 'from-slate-700 via-slate-600 to-zinc-700', glow: 'bg-slate-200' },
  { gradient: 'from-rose-700 via-pink-600 to-orange-600', glow: 'bg-rose-200' },
  { gradient: 'from-indigo-700 via-blue-600 to-violet-700', glow: 'bg-blue-200' },
  { gradient: 'from-orange-700 via-amber-700 to-violet-700', glow: 'bg-amber-200' },
  { gradient: 'from-indigo-700 via-purple-500 to-orange-600', glow: 'bg-violet-200' },
  { gradient: 'from-emerald-700 via-teal-600 to-cyan-700', glow: 'bg-emerald-200' },
  { gradient: 'from-cyan-700 via-sky-600 to-blue-700', glow: 'bg-cyan-200' },
] as const;

function stableSpaceThemeIndex(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash % SPACE_THEMES.length;
}

export function getSpaceTheme(fullName: string) {
  return SPACE_THEMES[stableSpaceThemeIndex(fullName.toLowerCase())];
}
