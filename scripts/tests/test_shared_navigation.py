import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "forgejo/custom/templates/custom/header.tmpl").read_text(encoding="utf-8")
FORGEJO_MANIFEST = ROOT / "forgejo/custom/public/assets/manifest.json"
FORGEJO_STYLES = (ROOT / "forgejo/custom/public/assets/css/nyankoface.css").read_text(encoding="utf-8")
PORTAL_MANIFEST = (ROOT / "frontend/app/manifest.ts").read_text(encoding="utf-8")
NAVIGATION = json.loads((ROOT / "frontend/public/nyankoface-navigation.json").read_text(encoding="utf-8"))
STYLESHEET_VERSION = "20260801-shared-navigation-brand-v1"
PREVIOUS_STYLESHEET_VERSION = "20260731-shared-navigation-v3"


class SharedNavigationContractTests(unittest.TestCase):
    def test_forgejo_uses_the_portal_manifest_as_its_only_custom_manifest(self):
        self.assertEqual(HEADER.count('<link rel="manifest"'), 1)
        self.assertIn('<link rel="manifest" href="/manifest.webmanifest">', HEADER)
        self.assertIn(
            'document.querySelector(\'link[rel="manifest"][href="/manifest.webmanifest"]\')',
            HEADER,
        )
        self.assertNotIn("/assets/manifest.json", HEADER)
        self.assertFalse(FORGEJO_MANIFEST.exists())
        self.assertIn("export const dynamic = 'force-dynamic'", PORTAL_MANIFEST)
        self.assertIn("const appName = getAppName()", PORTAL_MANIFEST)

    def test_forgejo_renders_audience_filtered_publish_items(self):
        self.assertEqual(
            [item["id"] for item in NAVIGATION["publish"]],
            ["create-repository", "mcp-administration", "administration"],
        )
        self.assertIn("const publishItems = Array.isArray(config.publish)", HEADER)
        self.assertIn("...config.community, ...publishItems", HEADER)
        self.assertIn("renderLinks(publishItems)", HEADER)

    def test_mobile_navigation_tracks_breakpoint_changes(self):
        self.assertIn('const mobileQuery = matchMedia("(max-width: 1199px)")', HEADER)
        self.assertIn('mobileMenu.classList.add("nyankoface-nav-menu-toggle")', HEADER)
        self.assertNotIn(
            'mobileMenu && mobileMenuToggle && matchMedia("(max-width: 1199px)").matches',
            HEADER,
        )
        self.assertIn('mobileQuery.addEventListener("change", syncMobileNavMenu)', HEADER)
        self.assertIn('mobileQuery.removeEventListener("change", syncMobileNavMenu)', HEADER)
        self.assertIn("if (!event.persisted) mobileQuery.removeEventListener", HEADER)
        self.assertIn('window.addEventListener("pageshow", (event)', HEADER)
        self.assertIn("if (event.persisted) syncMobileNavMenu()", HEADER)
        self.assertIn('document.body.classList.remove("nyankoface-mobile-navigation-open")', HEADER)

    def test_mobile_account_uses_forgejo_16_logout_action(self):
        self.assertIn('a.link-action[data-url*="/user/logout"]', HEADER)
        self.assertIn("renderedForgejoSession().logoutControl?.click()", HEADER)

    def test_mobile_account_fallback_uses_rendered_session_controls(self):
        fallback = HEADER.index("const renderMobileAccountFallback")
        canonical_fetch = HEADER.index('fetch("/nyankoface-navigation.json"')
        self.assertLess(fallback, canonical_fetch)
        self.assertIn("authenticated: Boolean(logoutControl)", HEADER)
        self.assertIn('logoutControl?.closest("details, .user-menu, .menu")', HEADER)
        self.assertIn("profileMenu?.querySelectorAll('a[href]')", HEADER)
        self.assertIn('[?&]tab=stars(?:&|$)', HEADER)
        self.assertIn('settingsLink?.getAttribute("href")', HEADER)
        self.assertIn('${japanese ? "プロフィール" : "Profile"}', HEADER)
        self.assertIn('${japanese ? "設定" : "Settings"}', HEADER)
        self.assertIn('data-nyankoface-mobile-logout', HEADER)
        self.assertIn('${japanese ? "ログイン" : "Log In"}', HEADER)
        self.assertIn('${japanese ? "新規登録" : "Sign Up"}', HEADER)
        self.assertIn('const loginHref = document.querySelector', HEADER)
        self.assertIn('const signupHref = document.querySelector', HEADER)
        self.assertEqual(HEADER.count("renderMobileAccountFallback"), 3)
        self.assertEqual(HEADER.count("bindMobileLogout("), 2)

    def test_forgejo_16_and_legacy_profile_dom_contracts_have_distinct_urls(self):
        forgejo_16 = '<details><div class="content"><a href="/qa-member">Profile</a><a href="/user/settings">Settings</a><a class="link-action" data-url="/user/logout"></a></div></details>'
        legacy = '<div class="ui dropdown"><div class="menu user-menu"><a href="/legacy-member">Profile</a><a href="/user/settings">Settings</a><a href="/user/logout"></a></div></div>'
        self.assertIn('href="/qa-member"', forgejo_16)
        self.assertIn('href="/legacy-member"', legacy)
        self.assertNotIn('href="/user/settings">Profile', forgejo_16 + legacy)

    def test_authenticated_tablet_navigation_hides_the_legacy_right_menu(self):
        self.assertIn("@media (max-width: 1199px)", HEADER)
        self.assertIn("body nav#navbar #mobile-notifications-icon", HEADER)
        self.assertIn(
            "body:not(.nyankoface-mobile-navigation-open) nav#navbar .navbar-right",
            HEADER,
        )
        self.assertIn(
            "body.nyankoface-mobile-navigation-open nav#navbar .navbar-right",
            HEADER,
        )
        self.assertIn(
            "body.nyankoface-mobile-navigation-open .nyankoface-mobile-menu-sheet",
            HEADER,
        )

    def test_mobile_navigation_sheet_scrolls_inside_short_viewports(self):
        self.assertIn("body.nyankoface-mobile-navigation-open .nyankoface-mobile-menu-sheet", FORGEJO_STYLES)
        self.assertIn("height: calc(100dvh - 64px)", FORGEJO_STYLES)
        self.assertIn("max-height: calc(100dvh - 64px)", FORGEJO_STYLES)
        self.assertIn("overflow-y: auto", FORGEJO_STYLES)
        self.assertIn("overscroll-behavior-y: contain", FORGEJO_STYLES)

    def test_forgejo_busts_the_cache_for_shared_navigation_styles(self):
        self.assertIn(f"/css/nyankoface.css?v={STYLESHEET_VERSION}", HEADER)
        self.assertNotIn(PREVIOUS_STYLESHEET_VERSION, HEADER)

    def test_forgejo_fallback_keeps_repositories_separate_from_models(self):
        fallback_icons = HEADER[HEADER.index("const navIcon = {"):HEADER.index("const navItems", HEADER.index("const navIcon = {"))]
        self.assertIn('folder: fontAwesomeIcon("folder"', fallback_icons)
        self.assertIn('models.className = "item nyankoface-nav-models"', HEADER)
        self.assertIn('models.href = "/models"', HEADER)
        self.assertIn('setText(explore, "Repositories")', HEADER)
        self.assertIn('explore.href = "/git/explore/repos"', HEADER)
        self.assertIn('if (query === "space") return "space";', HEADER)
        self.assertIn('if (query === "dataset") return "dataset";', HEADER)
        self.assertIn('if (query === "model") return "model";', HEADER)
        self.assertIn('return null;', HEADER[HEADER.index('const currentExploreKind'):HEADER.index('const enhanceExploreRepos')])
        self.assertIn('document.querySelector(".nyankoface-nav-models")?.classList.add("active")', HEADER)
        self.assertIn('<a class="active" href="/models">Main</a>', HEADER)
        self.assertIn('kind === "model" ? "/models"', HEADER)
        self.assertIn('<li><a href="/models">Models</a></li>', HEADER)
        self.assertNotIn('explore.href = "/models"', HEADER)


if __name__ == "__main__":
    unittest.main()
