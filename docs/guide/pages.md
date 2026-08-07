---
title: NyankoFace Pages
type: guide
description: Canonical workflow for publishing static HTML and generated documentation from public Forgejo repositories.
readingTime: 12 min
tags: [pages, vitepress, actions, static-site]
related:
  - title: Runtime model
    link: /wiki/runtime
  - title: Docker Spaces
    link: /guide/spaces
  - title: Troubleshooting
    link: /guide/troubleshooting
---

# NyankoFace Pages

This is the canonical NyankoFace Pages publishing workflow. Pages exposes already
built static files from a **public** Forgejo repository. It does not execute a
server and it does not require a `pages` repository topic.

## Choose the right surface

| Goal | Use |
| --- | --- |
| Static HTML/CSS/JavaScript, VitePress, Astro, or a static export | **Pages** |
| Gradio, Next.js server rendering, Streamlit, FastAPI, Node.js, or another running process | **Docker Space** |
| Markdown articles indexed in the NyankoFace Knowledge directory | **Knowledge** |

Pages can coexist with a Model, Dataset, Skill, or other catalog repository.
Repository topics classify the catalog entry; the Pages source contract alone
enables its static site.

## Detection contract

NyankoFace checks these locations on every repository-detail request, in order:

1. `index.html` at the root of the `gh-pages` branch;
2. `docs/index.html` on the repository's default branch.

The first existing file wins. A `gh-pages` branch without `index.html` does not
count as a deployment. Private repositories are never published.

The public URL is:

```text
https://HOST/pages/OWNER/REPOSITORY/
```

Generated sites must use this base path:

```text
/pages/OWNER/REPOSITORY/
```

## Which source should I use?

| Source | Choose it when | Trade-off |
| --- | --- | --- |
| `gh-pages` | A build produces HTML/CSS/JS, or source and output should be separated | Recommended for VitePress and CI; deployment can replace the branch |
| default-branch `docs/` | The checked-in files are already the final static site | Simplest Git-only workflow; source and public output share one branch |

Do not add both unless you intentionally want `gh-pages` to take precedence.

## Deploy from the NyankoFace interface

Open `/pages` and select **Deploy new Pages**, or use **Publish with Pages** on
any public repository that is not configured yet. The wizard never starts a
Space and requires no `pages` topic.

1. enter or select a public `OWNER/REPOSITORY`;
2. run the publishing-condition check;
3. choose `gh-pages`, default-branch `docs/`, or VitePress + Forgejo Actions;
4. review the exact branch and file paths that NyankoFace will create or replace;
5. confirm the changes and deploy;
6. review each log entry and commit SHA;
7. open **Visit site**, or open the Actions log while VitePress is building.

The deployment endpoint requires an authenticated Forgejo user with write
permission on that repository. It rechecks that the repository is public before
writing anything. A private repository, missing permission, failed write, or
failed Pages inspection is shown as an error instead of being treated as a
successful deployment.

## Publish the smallest static site

Start from a clean working tree. Replace the remote with the real Forgejo URL.

```bash
git switch --orphan gh-pages
git rm -rf .
cat > index.html <<'HTML'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hello from NyankoFace Pages</title>
  </head>
  <body><h1>Hello from NyankoFace Pages</h1></body>
</html>
HTML
git add index.html
git commit -m "docs: publish NyankoFace Pages site"
git push --force-with-lease origin gh-pages
```

For the `docs/` method, keep the default branch checked out, add
`docs/index.html`, commit, and push normally.

## VitePress and generated sites

Configure the repository-specific base path:

```ts
// docs/.vitepress/config.mts
import { defineConfig } from 'vitepress'

export default defineConfig({
  base: process.env.VITEPRESS_BASE ?? '/',
})
```

The seeded `nyankoface/vitepress-pages-starter` contains a working Forgejo Actions
workflow. Its essential steps are:

```yaml
name: Publish VitePress to NyankoFace Pages
on:
  push:
    branches: [main]
    paths: ['docs/**', 'package.json', 'package-lock.json']
  workflow_dispatch:

jobs:
  publish:
    runs-on: node20
    steps:
      - uses: https://data.forgejo.org/actions/checkout@v4
      - run: npm install --no-audit --no-fund
      - run: VITEPRESS_BASE="/pages/${GITHUB_REPOSITORY}/" npm run docs:build
      - name: Publish built output
        env:
          PAGES_TOKEN: ${{ github.token }}
        run: |
          git config user.name "NyankoFace Pages"
          git config user.email "pages@nyankoface.local"
          git checkout --orphan gh-pages
          git rm -rf .
          cp -R docs/.vitepress/dist/. .
          touch .nojekyll
          git add --all
          git commit -m "Publish Pages for ${GITHUB_SHA}"
          git remote set-url origin "http://oauth2:${PAGES_TOKEN}@forgejo:3000/${GITHUB_REPOSITORY}.git"
          git push --force origin gh-pages
```

Only built output belongs on `gh-pages`. Do not publish the VitePress project
source as if it were a deployable site.

## Verify the deployment

After each push:

1. open the repository detail page;
2. find the **NyankoFace Pages** card in the sidebar;
3. confirm the card shows **Published** and the expected source;
4. open **Visit site**;
5. check the root page, one CSS/JavaScript/image asset, and one nested route;
6. verify the public URL copy button.

The Navigator Skill includes a live checker:

```bash
python skills/nyankoface-navigator/scripts/verify_pages.py \
  https://HOST/pages/OWNER/REPOSITORY/ \
  --asset assets/app.css \
  --nested guide/
```

The runner and frontend use uncached inspection for the repository card, so a
new push is visible on the next page load.

## Updating, deleting, and making a site private

- **Update:** push new built files to the active source, then reload the
  repository page and public URL.
- **Switch source:** delete `gh-pages` before expecting default-branch `docs/`
  to become active.
- **Delete:** delete `gh-pages` and remove `docs/index.html`.
- **Make private:** change the Forgejo repository visibility to private.
  NyankoFace returns `404` and does not expose its Pages assets.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Pages card says **Not configured** | Add `gh-pages/index.html` or `<default>/docs/index.html`; the card lists both checks |
| `404` at the public URL | Confirm the repository is public, spelling/case of owner and repository, branch, and `index.html` |
| CSS/JS/images are missing | Build with `/pages/OWNER/REPOSITORY/` as the base and use relative or base-aware asset URLs |
| Nested routes return `404` | Static hosting requires a real file such as `guide/index.html`; server-side rewrites do not run |
| Card shows the wrong source | `gh-pages` always wins; delete it to use `docs/` |
| Card says **Unavailable** | Forgejo or the Pages runner could not be inspected; check service health and reload |
| Link preview is incomplete | Add `<title>`, Open Graph, Twitter card metadata, and a reachable preview image |

## Sharing metadata

NyankoFace preserves repository-authored values and fills only missing
`<title>`, Open Graph, and Twitter card fields. Relative preview-image paths are
resolved against the public Pages URL.

```html
<title>Human-readable page title</title>
<meta property="og:title" content="Human-readable page title">
<meta property="og:description" content="One concise summary">
<meta property="og:image" content="./social-card.png">
<meta name="twitter:card" content="summary_large_image">
```
