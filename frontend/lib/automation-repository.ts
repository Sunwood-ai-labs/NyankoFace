import {
  getPublicTextFileAtRevision,
  repoKind,
  resolvePublicRepoRevision,
} from './forgejo';
import {
  AUTOMATION_MAX_BYTES,
  AutomationPreflight,
  inspectAutomationToml,
} from './automation';

export interface AutomationRepositoryInspection {
  preflight: AutomationPreflight;
  toml: string;
}

export async function inspectPublicAutomationRepository(
  owner: string,
  repo: string,
  requestedRef?: string,
): Promise<AutomationRepositoryInspection | null> {
  const revision = await resolvePublicRepoRevision(owner, repo, requestedRef);
  if (!revision || repoKind(revision.repo.topics) !== 'automation') return null;
  const toml = await getPublicTextFileAtRevision(
    owner,
    repo,
    'automation.toml',
    revision.sha,
    AUTOMATION_MAX_BYTES,
  );
  if (toml === null) return null;
  return {
    toml,
    preflight: inspectAutomationToml(toml, {
      owner,
      repo,
      ref: revision.requestedRef,
      sha: revision.sha,
    }),
  };
}
