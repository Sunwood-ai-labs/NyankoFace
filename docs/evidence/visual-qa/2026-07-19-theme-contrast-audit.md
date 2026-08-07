# 全テーマ・全ページ コントラスト監査（2026-07-19）

NyankoFace の全登録画面について、テーマだけでなく OS の明暗設定も独立して切り替え、デスクトップ／モバイルの両方で WCAG コントラスト計算と実スクリーンショット確認を行いました。

## 結果

| 項目 | 結果 |
|---|---:|
| テーマ | Standard / Solarpunk / Cyberpunk |
| OS カラースキーム | light / dark |
| ビューポート | desktop 1440×1000 / mobile 390×844 |
| 登録ルート | 32 |
| 組み合わせ | 3 × 2 × 2 × 32 = **384** |
| 合格 | **384 / 384** |
| 計算した可視テキストノード | **20,196** |
| 画像背景として分離したテキストノード | **9,468** |
| 最小しきい値余裕 | **1.01×** |
| 目視確認 | **48 枚の全 contact sheet** |

通常テキストは 4.5:1、大文字・太字の大きなテキストは 3:1 を合格基準にしています。半透明色は実際の背景色へ合成してから計算します。画像背景上の文字は単一の背景色に還元すると誤判定になるため数値監査から分離し、原寸スクリーンショットと contact sheet で確認しました。

## 修正した主な箇所

- Cyberpunk の Skill 本文、関係カード、バッジ、Markdown
- Standard dark の Space 稼働状態バッジ
- Solarpunk のログイン継続リンク
- Cyberpunk dark の組織タブ
- Forgejo のリポジトリ一覧、Dataset Viewer、認証、組織、コミュニティ画面
- Skill のForgejo Files画面（ファイル名、最新コミット帯、ツールバー、表の連続エッジ）
- OS の `prefers-color-scheme` が選択中テーマへ混入する組み合わせ

## 代表スクリーンショット

| Cyberpunk / dark OS / Skill | Cyberpunk / light OS / Skill | Cyberpunk / dark OS / Skill relationships |
|---|---|---|
| ![Cyberpunk dark OS skill detail](../../images/visual-qa/2026-07-19/cyberpunk-dark-mobile-skill-detail.png) | ![Cyberpunk light OS skill detail](../../images/visual-qa/2026-07-19/cyberpunk-light-mobile-skill-detail.png) | ![Cyberpunk skill relationships](../../images/visual-qa/2026-07-19/cyberpunk-dark-mobile-skill-relationships.png) |

| Cyberpunk organization | Standard / dark OS / Space | Solarpunk / dark OS / Login |
|---|---|---|
| ![Cyberpunk organization](../../images/visual-qa/2026-07-19/cyberpunk-dark-mobile-organization.png) | ![Standard dark OS Space](../../images/visual-qa/2026-07-19/standard-dark-mobile-space.png) | ![Solarpunk dark OS login](../../images/visual-qa/2026-07-19/solarpunk-dark-mobile-login.png) |

### Skill Files：スクロール上・中・下

| Top | Middle | Bottom |
|---|---|---|
| ![Cyberpunk Skill Files top](../../images/visual-qa/2026-07-19/cyberpunk-mobile-skill-files-top.png) | ![Cyberpunk Skill Files middle](../../images/visual-qa/2026-07-19/cyberpunk-mobile-skill-files-middle.png) | ![Cyberpunk Skill Files bottom](../../images/visual-qa/2026-07-19/cyberpunk-mobile-skill-files-bottom.png) |

Files画面は3テーマ × desktop/mobile × top/middle/bottomの **18 / 18** スクロール撮影も合格しています。上部コミット帯とファイル表は単一の輪郭へ統合し、最下行の丸角まで目視確認しました。

## 再実行

```bash
npm ci --prefix visual-tests
npm exec --prefix visual-tests -- playwright install chromium
npm run capture:themes --prefix visual-tests
```

成果物は `visual-tests/artifacts/theme-matrix/` に生成されます。`manifest.json` に全ノードの計算結果、`screenshots/` に384枚の原寸画像、`contact-sheets/` に48枚の一覧画像が入ります。
