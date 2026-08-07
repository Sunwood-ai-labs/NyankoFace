import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  navigationItemIsCurrent,
  navigationItemsForAudience,
  nyankoFaceNavigation,
} from './navigation';
import { hasRenderedForgejoAdminControl } from './forgejo-session-types';

const navbarSource = readFileSync(new URL('../components/Navbar.tsx', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

test('canonical navigation keeps stable primary information architecture', () => {
  assert.deepEqual(
    nyankoFaceNavigation.primary.map((item) => item.id),
    ['models', 'datasets', 'spaces', 'pages', 'knowledge'],
  );
  const items = [
    ...nyankoFaceNavigation.primary,
    ...nyankoFaceNavigation.explore,
    ...nyankoFaceNavigation.community,
    ...nyankoFaceNavigation.publish,
  ];
  assert.equal(new Set(items.map((item) => item.id)).size, items.length);
  assert.ok(items.every((item) => item.href.startsWith('/') || item.external));
});

test('active matching covers descendants without making home globally active', () => {
  assert.equal(navigationItemIsCurrent('/', '/'), true);
  assert.equal(navigationItemIsCurrent('/models', '/'), false);
  assert.equal(navigationItemIsCurrent('/models/nyankoface/demo', '/models'), true);
  assert.equal(navigationItemIsCurrent('/datasets', '/models'), false);
  assert.equal(navigationItemIsCurrent('/git/explore/repos', '/git/explore/repos'), true);
  assert.equal(navigationItemIsCurrent('/git/explore/users', 'https://example.com'), false);
});

test('administration is only exposed to the admin audience', () => {
  assert.deepEqual(navigationItemsForAudience(nyankoFaceNavigation.publish, 'anonymous'), []);
  assert.deepEqual(
    navigationItemsForAudience(nyankoFaceNavigation.publish, 'authenticated').map((item) => item.id),
    ['create-repository'],
  );
  assert.deepEqual(
    navigationItemsForAudience(nyankoFaceNavigation.publish, 'admin').map((item) => item.id),
    ['create-repository', 'mcp-administration', 'administration'],
  );
});

test('mobile navigation closes when the viewport enters the desktop breakpoint', () => {
  assert.match(navbarSource, /matchMedia\('\(min-width: 1280px\)'\)/);
  assert.match(navbarSource, /if \(query\.matches\) setMobileOpen\(false\)/);
  assert.match(navbarSource, /desktopQuery\.addEventListener\('change', closeAtDesktop\)/);
  assert.match(navbarSource, /desktopQuery\.removeEventListener\('change', closeAtDesktop\)/);
});

test('desktop menus close on same-tab navigation and preserve modified clicks', () => {
  assert.match(navbarSource, /function isSameTabPrimaryClick/);
  assert.match(navbarSource, /!event\.metaKey/);
  assert.match(navbarSource, /!event\.ctrlKey/);
  assert.match(navbarSource, /onClick=\{closeDetailsOnNavigate\}/);
  assert.match(navbarSource, /details\.open = false/);
  assert.match(navbarSource, /setExploreOpen\(false\)/);
  assert.match(navbarSource, /setAccountOpen\(false\)/);
});

test('desktop menus dismiss outside the menu and restore focus on Escape', () => {
  assert.match(navbarSource, /function useDismissibleDetails/);
  assert.match(navbarSource, /document\.addEventListener\('pointerdown', onPointerDown\)/);
  assert.match(navbarSource, /event\.key !== 'Escape'/);
  assert.match(navbarSource, /triggerRef\.current\?\.focus\(\)/);
  assert.match(navbarSource, /onToggle=\{\(event\) => setExploreOpen\(event\.currentTarget\.open\)\}/);
  assert.match(navbarSource, /onToggle=\{\(event\) => setAccountOpen\(event\.currentTarget\.open\)\}/);
});

test('solarpunk keeps explicit navigation shell colors when the OS prefers dark', () => {
  assert.match(globalStyles, /html\[data-nyankoface-theme="solarpunk"\] \.nyankoface-explore-menu/);
  assert.match(globalStyles, /html\[data-nyankoface-theme="solarpunk"\] \.nyankoface-account-menu/);
  assert.match(globalStyles, /html\[data-nyankoface-theme="solarpunk"\] \.nyankoface-mobile-panel/);
  assert.match(globalStyles, /html\[data-nyankoface-theme="solarpunk"\] \.nyankoface-mobile-menu-toggle\[aria-expanded="true"\]/);
  assert.match(globalStyles, /html\[data-nyankoface-theme="solarpunk"\] \.nyankoface-explore-card:focus-visible/);
});

test('admin audience requires a rendered Forgejo administration control', () => {
  const memberSettings = `
    <p>Signed in as <strong>member</strong></p>
    <script>const mobileAdmin = '<a href="/git/admin">Administration</a>';</script>
    <style>.hint::after { content: '/admin'; }</style>
    <template><a href="/admin">Administration</a></template>
    <a href="/user/settings">Settings</a>
  `;
  assert.equal(hasRenderedForgejoAdminControl(memberSettings), false);

  const adminSettings = `${memberSettings}<nav><a class="item" href="/admin">Site administration</a></nav>`;
  assert.equal(hasRenderedForgejoAdminControl(adminSettings), true);
});
