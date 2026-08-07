# Issue #112 — Home Pages discovery visual QA

The feature branch was built and run locally while reading the live Forgejo
repository catalog and Pages status endpoint. The audit covers all
three NyankoFace themes at desktop (1440×1000) and mobile (390×844) sizes.

## Result

- 6/6 runtime routes passed the structural visual audit.
- Every viewport exposes separate **Pagesを見る** and **Pagesを公開する** actions.
- The live preview contains three genuinely published Pages sites.
- No horizontal overflow was detected.
- The standard, Solarpunk, and Cyberpunk screenshots were opened and reviewed.
- Published-card names, descriptions, owners, sources, update times, metrics,
  and public-site actions remain readable at both widths.

The machine-readable measurements are in [report.json](report.json). Each
theme includes a viewport screenshot and a full-height Pages-section capture.

## Mobile comparison

| Standard | Solarpunk | Cyberpunk |
| --- | --- | --- |
| ![Standard mobile Pages discovery](standard--mobile--anonymous--pages-discovery.png) | ![Solarpunk mobile Pages discovery](solarpunk--mobile--anonymous--pages-discovery.png) | ![Cyberpunk mobile Pages discovery](cyberpunk--mobile--anonymous--pages-discovery.png) |

## Desktop comparison

| Standard | Solarpunk | Cyberpunk |
| --- | --- | --- |
| ![Standard desktop home](standard--desktop--anonymous--classic-home.png) | ![Solarpunk desktop home](solarpunk--desktop--anonymous--classic-home.png) | ![Cyberpunk desktop home](cyberpunk--desktop--anonymous--classic-home.png) |
