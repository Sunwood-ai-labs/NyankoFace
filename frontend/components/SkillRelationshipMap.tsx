import Link from 'next/link';
import { Repo, SkillDependency } from '@/lib/forgejo';
import HfIcon from './HfIcon';
import { Locale, ui } from '@/lib/i18n';

type ResolvedDependency = SkillDependency & {
  owner: string;
  name: string;
  fullName: string;
  description?: string | null;
};

function splitReference(reference: string, fallbackOwner: string) {
  const [owner, ...nameParts] = reference.split('/');
  return nameParts.length
    ? { owner, name: nameParts.join('/') }
    : { owner: fallbackOwner, name: owner };
}

function matchesReference(reference: string, repo: Repo, fallbackOwner: string) {
  const resolved = splitReference(reference, fallbackOwner);
  const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
  return owner.toLowerCase() === resolved.owner.toLowerCase() && repo.name.toLowerCase() === resolved.name.toLowerCase();
}

function resolveDependency(dependency: SkillDependency, owner: string, catalog: Repo[]): ResolvedDependency {
  const reference = splitReference(dependency.repo, owner);
  const target = catalog.find((repo) => matchesReference(dependency.repo, repo, owner));
  return {
    ...dependency,
    owner: target?.owner?.login ?? reference.owner,
    name: target?.name ?? reference.name,
    fullName: target?.full_name ?? `${reference.owner}/${reference.name}`,
    description: target?.description,
  };
}

function RelationshipCard({ dependency, reverse = false, locale }: { dependency: ResolvedDependency; reverse?: boolean; locale: Locale }) {
  return (
    <Link
      href={`/${dependency.owner}/${dependency.name}`}
      data-skill-relationship-link
      className="skill-relationship-card group block rounded-xl border border-violet-100 bg-white/90 p-2.5 shadow-sm transition hover:border-violet-300 hover:shadow-md dark:border-violet-900/70 dark:bg-zinc-950/70"
    >
      <span className="flex min-w-0 items-center gap-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-violet-100 text-violet-700 ring-1 ring-violet-200 dark:bg-violet-950 dark:text-violet-300 dark:ring-violet-800">
          <HfIcon name={reverse ? 'fork' : 'skill'} className="h-3 w-3" />
        </span>
        <span className="skill-relationship-name min-w-0 flex-1 truncate font-mono text-[11px] font-bold text-zinc-900 group-hover:text-violet-800 dark:text-zinc-100 dark:group-hover:text-violet-300">
          {dependency.name}
        </span>
        <span className={`skill-relationship-badge shrink-0 rounded-full px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide ${dependency.type === 'required' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300' : 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300'}`}>
          {dependency.type === 'required' ? ui(locale, '必須', 'Required') : ui(locale, 'ワークフロー', 'Workflow')}
        </span>
      </span>
      <span className="skill-relationship-reason mt-2 block text-[11px] leading-4 text-zinc-600 dark:text-zinc-400">
        {dependency.reason || dependency.description || ui(locale, '関連するスキルワークフロー', 'Related Skill workflow')}
      </span>
      {dependency.evidence ? (
        <span className="skill-relationship-evidence mt-1.5 block border-l-2 border-violet-200 pl-2 text-[10px] leading-4 text-zinc-500 dark:border-violet-800 dark:text-zinc-500">
          <strong className="font-semibold text-zinc-600 dark:text-zinc-400">{ui(locale, 'SKILL.mdの根拠:', 'SKILL.md basis:')}</strong> {dependency.evidence}
        </span>
      ) : null}
    </Link>
  );
}

export default function SkillRelationshipMap({
  repo,
  catalog,
  placement,
  locale,
}: {
  repo: Repo;
  catalog: Repo[];
  placement: 'sidebar' | 'mobile';
  locale: Locale;
}) {
  const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
  const dependencies = (repo.skill_relationships?.dependencies || []).map((dependency) =>
    resolveDependency(dependency, owner, catalog),
  );
  const incoming = catalog.flatMap((candidate) => {
    const candidateOwner = candidate.owner?.login ?? candidate.full_name.split('/')[0];
    return (candidate.skill_relationships?.dependencies || [])
      .filter((dependency) => matchesReference(dependency.repo, repo, candidateOwner))
      .map((dependency) => ({
        ...dependency,
        owner: candidateOwner,
        name: candidate.name,
        fullName: candidate.full_name,
        description: candidate.description,
        reason: dependency.reason || candidate.description || undefined,
      }));
  });
  const requiredCount = dependencies.filter(({ type }) => type === 'required').length;
  const workflowCount = dependencies.length - requiredCount;
  const connectionCount = dependencies.length + incoming.length;
  const titleId = `skill-relationship-title-${placement}`;

  return (
    <section
      data-skill-relationship-map
      data-relationship-placement={placement}
      className="skill-relationship-panel overflow-hidden rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 via-white to-fuchsia-50/60 shadow-sm dark:border-violet-900 dark:from-violet-950/35 dark:via-zinc-950 dark:to-fuchsia-950/20"
      aria-labelledby={titleId}
    >
      <div className="skill-relationship-header flex items-center gap-2.5 border-b border-violet-100 px-3.5 py-3 dark:border-violet-900/70">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-violet-700 text-white shadow-md shadow-violet-200 dark:shadow-violet-950">
          <HfIcon name="link" className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-sm font-semibold text-zinc-950 dark:text-zinc-100">{ui(locale, 'スキルの関連', 'Skill relationships')}</h2>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">{ui(locale, `根拠付きリンク ${connectionCount}件`, `${connectionCount} evidence-backed link${connectionCount === 1 ? '' : 's'}`)}</p>
        </div>
        <Link
          href={`/${owner}/${repo.name}?tab=files&path=skill.json`}
          className="skill-relationship-metadata rounded-lg border border-violet-200 bg-white px-2 py-1 font-mono text-[9px] font-semibold text-violet-700 hover:border-violet-400 dark:border-violet-800 dark:bg-zinc-950 dark:text-violet-300"
        >
          {ui(locale, 'メタデータ', 'metadata')}
        </Link>
      </div>

      <div className={`grid gap-4 p-3.5 ${placement === 'mobile' ? 'sm:grid-cols-2' : ''}`}>
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="skill-relationship-section-title text-[10px] font-bold uppercase tracking-[0.14em] text-violet-700 dark:text-violet-300">{ui(locale, '使用／連携', 'Uses / works with')}</h3>
            <span className="text-[9px] text-zinc-400">{ui(locale, `必須 ${requiredCount} · ワークフロー ${workflowCount}`, `${requiredCount} required · ${workflowCount} workflow`)}</span>
          </div>
          <div className="grid gap-2">
            {dependencies.length ? dependencies.map((dependency) => (
              <RelationshipCard key={`${dependency.fullName}-${dependency.type}`} dependency={dependency} locale={locale} />
            )) : (
              <div className="skill-relationship-empty rounded-xl border border-dashed border-violet-200 bg-white/60 px-3 py-4 text-center dark:border-violet-900 dark:bg-zinc-950/40">
                <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{ui(locale, '単独で完結', 'Self-contained')}</p>
                <p className="mt-1 text-[10px] text-zinc-500">{ui(locale, '必須または推奨ワークフローのリンクはありません', 'No required or curated workflow link')}</p>
              </div>
            )}
          </div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="skill-relationship-section-title text-[10px] font-bold uppercase tracking-[0.14em] text-fuchsia-700 dark:text-fuchsia-300">{ui(locale, '参照元', 'Referenced by')}</h3>
            <span className="text-[9px] text-zinc-400">{ui(locale, '逆方向リンク', 'reverse links')}</span>
          </div>
          <div className="grid gap-2">
            {incoming.length ? incoming.map((dependency) => (
              <RelationshipCard key={`${dependency.fullName}-${dependency.type}`} dependency={dependency} reverse locale={locale} />
            )) : (
              <div className="skill-relationship-empty rounded-xl border border-dashed border-fuchsia-200 bg-white/60 px-3 py-4 text-center dark:border-fuchsia-900 dark:bg-zinc-950/40">
                <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{ui(locale, '参照元はありません', 'No reverse links')}</p>
                <p className="mt-1 text-[10px] text-zinc-500">{ui(locale, 'このスキルを参照するカタログ項目はまだありません', 'No catalog Skill points here yet')}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
