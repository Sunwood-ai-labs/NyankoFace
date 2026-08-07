# NyankoFaceブランド探索 — Issue #177

状態: デザイン探索は完了。production assetの置き換えは別の承認工程とする。
この証跡PRでは、現在のcanonicalなcat assetを意図的に変更していない。

## 証跡ファイル

- [10案比較ボード（PNG）](brand-exploration.png) · [SVG source](brand-exploration.svg)
- [縮小・配色matrix（PNG）](variant-matrix.png) · [SVG source](variant-matrix.svg)
- [10案のstandalone SVG](candidates/01-nyankoface-signal-wordmark.svg)、[02](candidates/02-open-eye.svg)、[03](candidates/03-neural-horizontal-face.svg)、[04](candidates/04-of-brain-line-monogram.svg)、[05](candidates/05-open-portal-wordmark.svg)、[06](candidates/06-cat-signal.svg)、[07](candidates/07-face-aperture.svg)、[08](candidates/08-community-wave.svg)、[09](candidates/09-black-wordmark-cyan-cut.svg)、[10](candidates/10-mark-first-monogram-system.svg)
- [English decision record](README.md)
- 再生成: `node docs/evidence/issues/177/build-brand-exploration.mjs`

boardはdeterministicなSVG primitive、明示した`viewBox`座標、high-contrastな
ink、cyan、amber accentを使い、全候補を同じ256-unit mark surfaceで比較する。
matrixはlight、dark、2色、monochrome、inverse、24/32px reductionを比較する。
指定されたreference language（minimal icon + wordmark、強いcontrast、horizontal
motion）は取り入れるが、Ideogramのlogo、typography、line patternはcopyしない。

## 10案

| # | 方向性 | 長所 | リスク | 想定surface |
|---|---|---|---|---|
| 01 | NyankoFace Signal Wordmark | open faceとsignalを読め、24pxでも強く、wordmarkへ拡張しやすい | line spacingを誤るとgenericなmenuに見える | Navbar、wordmark、favicon、social card |
| 02 | Open Eye | friendlyでeye apertureが明快、community向き | faviconでは識別性が下がり、eye-only productに見える | Navbar、onboarding、community |
| 03 | Neural Horizontal Face | face、signal、local AIのlayerを直接統合 | 小さくするとfaceの読みが弱くなる | favicon、dashboard、loading |
| 04 | OF Brain-Line Monogram | OF monogramとneural解釈を両立 | 右側のstrokeが多くcompact版が必要 | wordmark、developer docs、social card |
| 05 | Open Portal Wordmark | repositoryとopen boundaryの意味が伝わる | developer toolにありがちなportal記号になる | docs、Pages、repository shell |
| 06 | Cat Signal | 現行catとの連続性を保ちつつ簡略化できる | mascotへの依存が残りneutral化を制限する | Navbar、community、移行期間 |
| 07 | Face Aperture | 「Open」をloadingやtransitionのmotionへ展開できる | slitがmenuやequalizerに誤読される | loading、favicon、motion accent |
| 08 | Community Wave | user、agent、repositoryの接続をnode clichéなしで表現 | 24pxでface/nameとの結び付きが弱い | community、social card、event |
| 09 | Black Wordmark + Cyan Cut | monochrome、favicon、printで最も堅牢、cyanでNyankoFace色を残す | 移行中はwordmark併記が必要 | favicon、monochrome、print、Git hosting |
| 10 | Mark-First Monogram System | compact markからwordmarkまでresponsiveに設計できる | communityよりapp icon寄りになる | PWA、app icon、responsive header |

## 評価と暫定選定

scoreはIssueの基準、すなわちname/meaning、24px識別性、system展開性、
continuity、差別化を1–5で評価したもの。user researchやtrademark clearanceではない。

| # | Meaning | 24px | System | Continuity | Distinctive | Total | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| 01 | 5 | 5 | 5 | 3 | 4 | 22 | primary shortlist |
| 02 | 4 | 4 | 4 | 2 | 3 | 17 | 今回は見送り |
| 03 | 4 | 4 | 5 | 3 | 4 | 20 | 今回は見送り |
| 04 | 5 | 3 | 4 | 3 | 4 | 19 | 今回は見送り |
| 05 | 4 | 5 | 5 | 2 | 4 | 20 | 今回は見送り |
| 06 | 4 | 4 | 4 | 5 | 3 | 20 | continuity shortlist |
| 07 | 4 | 5 | 4 | 3 | 4 | 20 | 今回は見送り |
| 08 | 3 | 3 | 4 | 2 | 4 | 16 | 今回は見送り |
| 09 | 5 | 5 | 5 | 3 | 5 | 23 | utility shortlist |
| 10 | 4 | 4 | 5 | 3 | 4 | 20 | 今回は見送り |

暫定選定は次の3案とする。

1. **01 — NyankoFace Signal Wordmark** をprimary候補とする。「Open」「Face」、
   local signal、portal外でも成立するwordmarkの組み合わせが最も明快。
2. **06 — Cat Signal** をcontinuity候補とする。既存userに対する移行リスクを
   下げ、mascotを残すべきかを検証できる。
3. **09 — Black Wordmark + Cyan Cut** をutility候補とする。monochrome、favicon、
   print、code hostingのfallbackとして最も安全。

production採用前に短いuser preference test、trademark search、実runtime captureを行う。
この選定は暫定であり、法的clearanceやuser validationの完了を意味しない。

## 採用handoff

承認後はprimary systemを1つだけ実装する。planned asset familyは次の通り。

- full markの`primary-logo.svg`と`primary-logo.png`;
- Navbarとfaviconの24/32px用`compact-mark.svg`;
- wide headerとsocial card用`wordmark.svg`;
- thin strokeを使わないmonochrome／inverse variant;
- 16/32/48px favicon、`apple-icon.png`、PWA 192/512px icon、docs logo、
  Forgejo logo、social-card artworkの再生成;
- version付きcache suffixと`/git/`で安全なabsolute asset path。

実装PRではNavbar、footer、login、404/error、empty state、docs、PWA manifest、
Forgejo shellをdesktop（1024px以上）／mobile（480px以下）、Standard／Solarpunk／
Cyberpunk、OS light/darkで確認する。userが作成したPage／Spaceのlogoは変更しない。
実装PRが承認されるまでは現在のcanonical assetをliveのままにする。

## 受入チェックリスト

- [x] 10個のSVG候補、concept、長所、リスク、surface note。
- [x] light/dark、2色、monochrome、inverse、24px、32pxの比較。
- [x] 3候補のshortlist、score、選定理由。
- [x] production asset family、cache、base-path、migration plan。
- [x] 日英decision recordと再現可能なSVG generator。
- [ ] user preference、trademark、承認後のruntime実装。これは次の承認gateであり、
      本Issueの探索証跡では完了扱いにしない。
