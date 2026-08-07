import { ModelCardFrontmatter, languageList } from '@/lib/markdown';
import HfIcon from './HfIcon';

export default function CardBadges({
  frontmatter,
  basePath = '/models',
}: {
  frontmatter: ModelCardFrontmatter;
  basePath?: '/models' | '/datasets' | '/spaces' | '/skills' | '/mcps' | '/prompts' | '/docs' | '/characters' | '/benchmarks' | '/automations';
}) {
  const { license, pipeline_tag, tags } = frontmatter;
  const languages = languageList(frontmatter.language);

  const hasAny = license || pipeline_tag || languages.length > 0 || (tags && tags.length > 0);
  if (!hasAny) return null;

  return (
    <div className="mb-6 flex flex-wrap gap-2">
      {license && (
        <a href={`${basePath}?q=${encodeURIComponent(`license ${license}`)}`} className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800 ring-1 ring-blue-100 hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:ring-blue-800">
          <HfIcon name="file" className="h-3 w-3" />
          license: {license}
        </a>
      )}
      {pipeline_tag && (
        <a href={`${basePath}?q=${encodeURIComponent(pipeline_tag)}`} className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900 ring-1 ring-amber-100 hover:bg-amber-100 dark:bg-amber-900/20 dark:text-amber-300 dark:ring-amber-800">
          <HfIcon name="gear" className="h-3 w-3" />
          {pipeline_tag}
        </a>
      )}
      {languages.map((lang) => (
        <a
          key={lang}
          href={`${basePath}?q=${encodeURIComponent(lang)}`}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-800 ring-1 ring-indigo-100 hover:bg-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-300 dark:ring-indigo-800"
        >
          <HfIcon name="globe" className="h-3 w-3" />
          {lang}
        </a>
      ))}
      {(tags || []).map((tag) => (
        <a
          key={tag}
          href={`${basePath}?q=${encodeURIComponent(tag)}`}
          className="rounded-md bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-200 hover:text-zinc-900 dark:bg-zinc-800 dark:text-zinc-300"
        >
          #{tag}
        </a>
      ))}
    </div>
  );
}
