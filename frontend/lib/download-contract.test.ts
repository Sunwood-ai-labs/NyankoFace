import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const downloadLink = readFileSync(
  new URL('../components/DownloadLink.tsx', import.meta.url),
  'utf8',
);
const automationPanel = readFileSync(
  new URL('../components/AutomationPreflightPanel.tsx', import.meta.url),
  'utf8',
);
const automationRoute = readFileSync(
  new URL('../app/api/automations/[owner]/[repo]/bundle/route.ts', import.meta.url),
  'utf8',
);
const downloadRoute = readFileSync(
  new URL('../app/api/download/[owner]/[repo]/route.ts', import.meta.url),
  'utf8',
);

test('creates a fresh download operation key for every normal click', () => {
  assert.match(downloadLink, /searchParams\.set\('download_id', downloadId\)/);
  assert.doesNotMatch(downloadLink, /data-download-id/);
});

test('counts only the Automation download action, not copy-to-clipboard', () => {
  assert.match(automationPanel, /const blob = await requestBundle\(\);[\s\S]*navigator\.clipboard\.writeText/);
  assert.match(automationPanel, /const downloadId = globalThis\.crypto\?\.randomUUID/);
  assert.match(automationPanel, /const blob = await requestBundle\(downloadId\);[\s\S]*URL\.createObjectURL/);
});

test('records Automation success only from the completed response stream', () => {
  assert.match(automationRoute, /const responseBody = new ReadableStream[\s\S]*recordOutcome\('success'\)[\s\S]*new NextResponse\(responseBody/);
  assert.doesNotMatch(automationRoute, /const bundle = buildDisabledAutomationBundle[\s\S]*recordDownloadMetric\([\s\S]*idempotencyKey: `automation:\$\{downloadId\}:success`[\s\S]*return new NextResponse\(bundle/);
});

test('does not advertise compressed upstream bytes as the decoded stream length', () => {
  assert.match(downloadRoute, /headers: \{ 'Accept-Encoding': 'identity' \}/);
  assert.match(downloadRoute, /const contentEncoding = upstream\.headers\.get\('content-encoding'\);[\s\S]*if \(length && !contentEncoding\) headers\.set\('Content-Length', length\)/);
});
