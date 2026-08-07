# Issue #178 — navigationとbrandのruntime証跡

強化したnavigation/brand auditを、2026-08-05にlocal NyankoFace runtime
`https://localhost:8443`へ実行した。anonymousのportal／Forgejo 18 routeを、desktop
（1440px）とmobile（390px）で確認している。

## 結果

- [機械可読audit](latest-audit.json)
- [audit report](REPORT.md)
- [desktop/mobile visual packet](captures/AGENT_REVIEW.md)
- [capture manifest](captures/manifest.json)
- [screenshot](captures/screenshots/desktop--home.png)、[desktop Explore](captures/screenshots/desktop--global-nav-explore.png)、[desktop Forgejo](captures/screenshots/desktop--forgejo-home.png)、[desktop login](captures/screenshots/desktop--login.png)、[mobile home](captures/screenshots/mobile--home.png)、[mobile Explore](captures/screenshots/mobile--global-nav-explore.png)、[mobile Forgejo](captures/screenshots/mobile--forgejo-home.png)、[mobile login](captures/screenshots/mobile--login.png)

18 runtime caseはすべてpassした。versioned navigation manifest、canonical markの
wiring、favicon/PWA asset family、legacy logo referenceの不在、horizontal overflowの
source checkもpassしている。docs base URLをruntime packetへ設定していないため、docs
routeはskipとして記録した。

visual packetにはportal home、Explore menu、Forgejo home、loginをdesktop/mobileの
両方で収録した。screenshotはmanual reviewの証跡であり、CI gateにはしない。今回の
packetはanonymousのみなので、credentialを用意できるdeploymentではauthenticated／
admin stateを追加してauditする。

## 再現

```powershell
$env:NAVIGATION_BRAND_BASE_URL = 'https://localhost:8443'
$env:NAVIGATION_BRAND_OUTPUT_DIR = 'docs/evidence/issues/178'
npm run audit:navigation-brand --prefix visual-tests

$env:VISUAL_QA_BASE_URL = 'https://localhost:8443'
$env:VISUAL_QA_OUTPUT_DIR = 'docs/evidence/issues/178/captures'
$env:VISUAL_QA_ROUTES = 'home,global-nav-explore,forgejo-home,login'
npm run capture --prefix visual-tests
```
