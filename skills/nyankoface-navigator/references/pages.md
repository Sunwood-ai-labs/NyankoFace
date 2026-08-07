# NyankoFace Pages workflow

Use this reference when the requested output is a static site or generated
documentation. The canonical public guide is
`https://sunwood-ai-labs.github.io/NyankoFace/guide/pages`.

## 1. Confirm that Pages is the correct surface

- Choose **Pages** for built HTML/CSS/JavaScript.
- Choose **Docker Space** when a server process must keep running.
- Choose **Knowledge** for Markdown articles indexed by NyankoFace.

Pages is an additional publishing surface. It does not use a `pages` repository
topic and can coexist with another catalog type.

## 2. Inspect before changing files

```bash
git status --short --branch
git remote -v
git branch --all
git ls-tree -r gh-pages --name-only 2>/dev/null | head
test -f docs/index.html && printf 'docs source exists\n'
```

Confirm:

- the Forgejo repository is public;
- `OWNER` and `REPOSITORY` match the public URL exactly;
- whether source files are already built output or need a build;
- whether `gh-pages` or default-branch `docs/` should be authoritative.

Never infer that an existing branch is deployable. It must contain
`index.html`.

## 3. Choose one source

### Built output or CI: `gh-pages`

Use `assets/pages-static/index.html` for plain HTML or copy
`assets/pages-vitepress/` for VitePress. Build source on the default branch and
place only the built output at the root of `gh-pages`.

### Checked-in final files: `docs/`

Place the complete static site under `docs/`, including `docs/index.html`.
Do not create `gh-pages`, because it takes precedence.

## 4. Configure the base path

Generated sites must use:

```text
/pages/OWNER/REPOSITORY/
```

For VitePress:

```ts
base: process.env.VITEPRESS_BASE ?? '/'
```

and build with:

```bash
VITEPRESS_BASE="/pages/OWNER/REPOSITORY/" npm run docs:build
```

## 5. Validate locally

Pass the real Forgejo topic list when it is available. `pages` is not required.

```bash
python scripts/validate_repo.py REPOSITORY_PATH --goal pages --topics model
```

Resolve every `ERROR`. An intentional warning that `gh-pages` takes precedence
must still be explained to the user.

Also inspect the actual output:

```bash
test -f docs/.vitepress/dist/index.html   # generated docs before deployment
git ls-tree -r gh-pages --name-only       # existing deployed branch
```

## 6. Publish

For a small static `gh-pages` deployment:

```bash
git switch --orphan gh-pages
git rm -rf .
cp PATH_TO_BUILT_OUTPUT/. .
touch .nojekyll
git add --all
git diff --cached --check
git commit -m "docs: publish NyankoFace Pages site"
git push --force-with-lease origin gh-pages
```

For `docs/`, commit and push the final files on the default branch normally.
For VitePress automation, use
`assets/pages-vitepress/.forgejo/workflows/publish-pages.yml`.

## 7. Live-check the result

The public URL is:

```text
https://HOST/pages/OWNER/REPOSITORY/
```

Run:

```bash
python scripts/verify_pages.py \
  https://HOST/pages/OWNER/REPOSITORY/ \
  --asset assets/app.css \
  --nested guide/
```

Then verify in a real browser at desktop and mobile widths:

1. repository detail shows the **NyankoFace Pages** card;
2. status is **Published** and the source is correct;
3. **Visit site** opens the exact public URL;
4. **Copy public URL** copies that URL;
5. the root, one asset, and one nested page render correctly.

For a missing deployment, report the failed locations shown by the card:

- `gh-pages/index.html`
- `<default-branch>/docs/index.html`

Do not claim publication from a successful build alone.

## 8. Update, remove, or make private

- Update by pushing new built output to the active source.
- Delete `gh-pages` before switching to `docs/`.
- Remove both supported `index.html` locations to unpublish.
- Making the Forgejo repository private must make Pages return `404`.

Never work around the public-only policy with an administrator token, proxy
exception, or copied private asset.
