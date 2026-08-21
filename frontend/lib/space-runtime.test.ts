import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatElapsedDuration,
  getSpaceRuntimeState,
  isSpaceGatewayErrorDocument,
  isSpaceRuntimePending,
  isSpaceGatewayPending,
  normalizeSpaceRuntime,
  spaceRuntimePollInterval,
} from './space-runtime';

test('normalizes runner states without hiding startup and offline phases', () => {
  assert.deepEqual(normalizeSpaceRuntime({ status: 'warming', execution: 'remote-gpu' }), {
    status: 'leased',
    phase: 'warming',
    execution: 'remote-gpu',
  });
  assert.equal(normalizeSpaceRuntime({ state: 'starting' }).phase, 'starting');
  assert.equal(normalizeSpaceRuntime({ status: 'worker-offline' }).phase, 'offline');
  assert.equal(normalizeSpaceRuntime({ status: 'build_failed' }).phase, 'failed');
  assert.equal(normalizeSpaceRuntime({ status: 'running' }).status, 'running');
  assert.deepEqual(normalizeSpaceRuntime({ status: 'cancel_requested', execution: 'remote-gpu' }), {
    status: 'stopping',
    phase: 'stopping',
    execution: 'remote-gpu',
  });
  assert.deepEqual(normalizeSpaceRuntime({ status: 'cancelled', execution: 'remote-gpu' }), {
    status: 'stopped',
    phase: 'stopped',
    execution: 'remote-gpu',
  });
});

test('recognizes transient gateway responses that require an iframe retry', () => {
  assert.equal(isSpaceGatewayPending('{"error":"space is not running"}'), true);
  assert.equal(isSpaceGatewayPending('Space is still starting'), true);
  assert.equal(isSpaceGatewayPending('Space is not ready yet'), true);
  assert.equal(isSpaceGatewayPending('<main>Application ready</main>'), false);
  assert.equal(
    isSpaceGatewayErrorDocument('{"error":"remote GPU runtime is unavailable"}', 'application/json'),
    true,
  );
  assert.equal(isSpaceGatewayErrorDocument('{"result":"ready"}', 'application/json'), false);
  assert.equal(isSpaceGatewayErrorDocument('<main>Application ready</main>', 'text/html'), false);
});

test('polls transitional states faster than stable states', () => {
  assert.equal(spaceRuntimePollInterval('building'), 2_000);
  assert.equal(spaceRuntimePollInterval('running'), 10_000);
  assert.equal(spaceRuntimePollInterval('stopped'), 15_000);
  assert.equal(spaceRuntimePollInterval('offline'), 20_000);
});

test('reports pending phases and stable elapsed labels', () => {
  assert.equal(isSpaceRuntimePending('checking'), true);
  assert.equal(isSpaceRuntimePending('warming'), true);
  assert.equal(isSpaceRuntimePending('running'), false);
  assert.equal(formatElapsedDuration(9_900), '9s');
  assert.equal(formatElapsedDuration(65_000), '1:05');
});

test('maps runtime phases to persistent waiting-state rules', () => {
  assert.deepEqual(getSpaceRuntimeState('stopped'), {
    kind: 'available',
    currentStep: 'availability',
    nextStep: 'queue',
    isProgressing: false,
    canStart: true,
    canRetry: false,
  });
  assert.deepEqual(getSpaceRuntimeState('checking'), {
    kind: 'checking',
    currentStep: 'availability',
    nextStep: 'queue',
    isProgressing: true,
    canStart: false,
    canRetry: false,
  });
  assert.equal(getSpaceRuntimeState('offline').canStart, false);
  assert.equal(getSpaceRuntimeState('queued').currentStep, 'queue');
  assert.equal(getSpaceRuntimeState('warming').currentStep, 'prepare');
  assert.equal(getSpaceRuntimeState('failed').canRetry, true);
});
