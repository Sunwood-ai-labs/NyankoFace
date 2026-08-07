import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildPipelineDispatchRequest,
  pipelineTargetRevision,
} from './pipeline';

test('dispatches the default-branch workflow with a separate target revision', () => {
  assert.deepEqual(
    buildPipelineDispatchRequest({
      workflow: 'nyankoface-pipeline.yml',
      defaultBranch: 'main',
      targetRevision: `  ${'a'.repeat(40)}  `,
      environment: 'staging',
      runner: 'node20',
    }),
    {
      workflow: 'nyankoface-pipeline.yml',
      ref: 'main',
      environment: 'staging',
      inputs: {
        approve_production: 'false',
        runner: 'node20',
        revision: 'a'.repeat(40),
      },
    },
  );
});

test('omits an empty deployment target and preserves production approval', () => {
  assert.deepEqual(
    buildPipelineDispatchRequest({
      workflow: 'nyankoface-pipeline.yml',
      defaultBranch: 'trunk',
      targetRevision: '  ',
      environment: 'production',
      runner: 'gpu',
    }),
    {
      workflow: 'nyankoface-pipeline.yml',
      ref: 'trunk',
      environment: 'production',
      inputs: {
        approve_production: 'true',
        runner: 'gpu',
      },
    },
  );
});

test('prefers the reconciled deployment SHA when displaying a run target', () => {
  assert.equal(
    pipelineTargetRevision({
      deploymentSourceSha: 'c'.repeat(40),
      deployedRevision: 'release-v1',
      headSha: 'd'.repeat(40),
    }),
    'c'.repeat(40),
  );
  assert.equal(
    pipelineTargetRevision({
      deployedRevision: 'release-v1',
      headSha: 'd'.repeat(40),
    }),
    'release-v1',
  );
});
