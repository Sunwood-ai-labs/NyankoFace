export type PipelineDispatchRequest = {
  workflow: string;
  ref: string;
  environment: string;
  inputs: {
    approve_production: 'true' | 'false';
    runner: string;
    revision?: string;
  };
};

export function buildPipelineDispatchRequest({
  workflow,
  defaultBranch,
  targetRevision,
  environment,
  runner,
}: {
  workflow: string;
  defaultBranch: string;
  targetRevision: string;
  environment: string;
  runner: string;
}): PipelineDispatchRequest {
  const revision = targetRevision.trim();
  return {
    workflow,
    ref: defaultBranch,
    environment,
    inputs: {
      approve_production: environment === 'production' ? 'true' : 'false',
      runner,
      ...(revision ? { revision } : {}),
    },
  };
}

export function pipelineTargetRevision({
  deploymentSourceSha,
  deployedRevision,
  headSha,
}: {
  deploymentSourceSha?: string;
  deployedRevision?: string;
  headSha: string;
}): string {
  return deploymentSourceSha || deployedRevision || headSha;
}
