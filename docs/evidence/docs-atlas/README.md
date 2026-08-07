# Editorial knowledge atlas verification

Verified: 2026-07-21

NyankoFace documentation now combines three reading modes instead of treating every page as an undifferentiated manual:

- **Field notes** explain context, decisions, and evidence.
- **Knowledge atlas nodes** provide stable concept reference.
- **Practical guides** provide commands and procedures.

English and Japanese pages share the same slug inventory, frontmatter contract, navigation model, and related-reading graph.

## Automated checks

```text
npm run docs:check  PASS
npm run docs:build  PASS
browser console     0 errors / 0 warnings
desktop overflow    false at 1440 × 1000
mobile overflow     false at 390 × 844
GitHub CI            PASS (run 29833110449)
Docs + Pages deploy  PASS (run 29833110352)
```

The mobile platform-map table uses a local horizontal scroll container; the page itself does not overflow.

## Browser evidence

| English desktop | English dark theme |
|---|---|
| ![English editorial home](home-en-desktop.png) | ![English editorial home in dark theme](home-en-dark.png) |

| Japanese mobile home | Japanese mobile article |
|---|---|
| ![Japanese editorial home on mobile](home-ja-mobile.png) | ![Japanese field note on mobile](article-ja-mobile.png) |

| Knowledge node | Mobile navigation |
|---|---|
| ![Platform map knowledge node](wiki-platform-map.png) | ![Expanded Japanese mobile navigation](mobile-navigation-open.png) |

### Published GitHub Pages

![Published editorial home after the successful Pages deployment](production-home.png)

The published home returned the expected `NyankoFace Field Manual | NyankoFace` title without horizontal overflow. Clicking **Open the knowledge atlas** navigated to `/NyankoFace/wiki/` and rendered the atlas index.

Additional captures preserve the scrolled Japanese home and the mobile Wiki table. The dark-theme switch and mobile navigation were clicked in the real VitePress site before the screenshots were recorded.
