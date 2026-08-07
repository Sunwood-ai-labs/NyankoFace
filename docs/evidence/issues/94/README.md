# Issue #94 syntax highlighting visual QA

- Runtime: local Next.js development server connected to a local Forgejo dataset
- Visual capture is manual evidence and is not executed by CI.
- Coverage: 12 viewport screenshots
- Result: PASS

| Result | Theme | Viewport | Surface | Language | Page overflow | Internal overflow | Screenshot |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| PASS | standard-light | desktop | Knowledge article · YAML | yaml | 0px | 0px | [view](screenshots/standard-light--desktop--article-yaml.png) |
| PASS | standard-light | desktop | Repository README · unknown language fallback | text | 0px | 0px | [view](screenshots/standard-light--desktop--readme-unknown-language.png) |
| PASS | standard-light | mobile | Knowledge article · YAML | yaml | 0px | 20px | [view](screenshots/standard-light--mobile--article-yaml.png) |
| PASS | standard-light | mobile | Repository README · unknown language fallback | text | 0px | 169px | [view](screenshots/standard-light--mobile--readme-unknown-language.png) |
| PASS | standard-dark | desktop | Knowledge article · YAML | yaml | 0px | 0px | [view](screenshots/standard-dark--desktop--article-yaml.png) |
| PASS | standard-dark | desktop | Repository README · long plain text | text | 0px | 1068px | [view](screenshots/standard-dark--desktop--readme-long-line.png) |
| PASS | standard-dark | mobile | Knowledge article · YAML | yaml | 0px | 20px | [view](screenshots/standard-dark--mobile--article-yaml.png) |
| PASS | standard-dark | mobile | Repository README · long plain text | text | 0px | 1774px | [view](screenshots/standard-dark--mobile--readme-long-line.png) |
| PASS | cyberpunk | desktop | Knowledge article · YAML | yaml | 0px | 0px | [view](screenshots/cyberpunk--desktop--article-yaml.png) |
| PASS | cyberpunk | desktop | Repository README · long plain text | text | 0px | 1068px | [view](screenshots/cyberpunk--desktop--readme-long-line.png) |
| PASS | cyberpunk | mobile | Knowledge article · YAML | yaml | 0px | 20px | [view](screenshots/cyberpunk--mobile--article-yaml.png) |
| PASS | cyberpunk | mobile | Repository README · long plain text | text | 0px | 1774px | [view](screenshots/cyberpunk--mobile--readme-long-line.png) |

## Review inventory

- Article and repository README use the same header, tokens, copy control, focus behavior, and scroll container.
- Standard light, Standard dark, and Cyberpunk update from CSS theme tokens without re-highlighting.
- Desktop and 390px mobile pages do not gain horizontal page overflow.
- Long source lines scroll inside the code block; unknown languages remain escaped plain text.
- Copy is exercised with a real click and checked against the browser clipboard.
- Exploratory cases: an unknown `env` fence and a 272-character README line.
- The imported `draw-io-skill` README references upstream images that return 404 in the seed dataset. Those resource warnings are recorded in `audit.json`; they predate this renderer change and are not application console errors.

## Environment note

The public access path exceeded 120 seconds during the first article request. The final audit used a local HTTP endpoint; this isolates transport latency from renderer QA.
