## Imported Claude Cowork project instructions

## Local-only deployment context

このリポジトリに`agent.local.md`がある場合は、マシン固有の自宅・ローカル環境情報をそこから確認する。`agent.local.md`はGitへコミット・pushせず、公開ドキュメントへ転記しない。パスワード、APIキー、アクセストークン、秘密鍵の内容はどのファイルにも記載しない。

## Project links

- Issue窓口: https://github.com/Sunwood-ai-labs/NyankoFace/issues

## Git commit policy

すべてのファイル変更を伴う実装タスクは、最終応答の前に git コミットで終了する必要があります。

- 編集前に `git status` を確認し、事前に存在する変更や同時変更をユーザー所有とみなしてください。
- コミット前に最終的な diff をレビューし、適切な検証を実行してください。
- 現在のタスクに属するファイルまたはハンクのみをステージングしてください。ユーザーが明示的に要求しない限り、関連のない変更をバンドルしないでください。
- `main` に対して簡潔で記述的なコミットメッセージを使用し、コミットハッシュを報告してください。要求がない限り、プッシュ、アマンド、または履歴の書き換えを行わないでください。
- 読み取り専用タスクおよびファイル変更がないタスクは、空のコミットを作成しません。

## Delivery time policy

- 実装前にIssueのscopeと受入条件を固定し、25 files、2,000 changed lines、20 commitsのいずれかを超える見込みなら、独立して検証・配備できるPRへ分割してください。
- 実装中は45分以内ごとに、検証可能なcoherent checkpointをcommitしてください。安全にcommitできない場合は、無言で作業を継続せず、Issueまたは進捗報告へblockerと次の判断点を記録してください。
- 同じ失敗が2回続いたら、3回目を試す前に原因を切り分けてください。別機能や別障害を現在のPRへ追加せず、別Issueへ分離してください。
- reviewはmicro-commitごとに依頼せず、対象testが通る安定したheadへまとめて依頼してください。merge前には `scripts/check_pr_merge_readiness.py` を実行し、exact-head review、未解決thread 0、登録済みCI成功を確認してください。
- 視覚captureをCIへ追加しないでください。Visual QAは実runtimeを手動captureし、人が画像を開いて確認します。

## Git worktree policy

- ファイル変更を伴うIssueは、原則としてIssue専用branchと専用worktreeで開始してください。例: `git worktree add ../NyankoFace-issue-123 -b fix/issue-123 main`。
- repository rootのmain worktreeは、最新mainの同期、統合test、merge後の本番反映だけに使い、feature実装を直接行わないでください。
- 複数Issueが同じfileまたは同じ状態schemaを変更する場合は並行編集せず、依存PRを先にmergeしてから後続worktreeを最新mainへ更新してください。
- 各worktreeは1 Issue、1 acceptance criteria set、1 PRに限定してください。途中で見つけた別問題は別Issue・別worktreeへ分離してください。
- PR mergeと本番確認が完了したら、未push commitやユーザー所有変更がないことを確認してからworktreeとlocal branchを削除してください。

## Parallel agent and CLI-first policy

- 独立したIssueでwrite setとstate schemaが重ならない場合は、可能な限りサブエージェントへboundedな監査・実装・検証を分担し、Issueごとの専用worktreeで並列処理してください。各agentの担当範囲、対象Issue、変更ファイルを開始時に固定してください。
- 同一file、共有config、DB／registry schema、API contractを触るIssueは並列編集せず、先行PRのmerge後に後続worktreeを最新mainへ更新してください。agentの結果は必ずmain agentがdiff、test、scopeを確認してから統合してください。
- 1 Issue＝1 acceptance criteria set＝1専用worktree＝1 PRを維持し、複数Issueの変更・レビュー・mergeを一つのPRへ混在させないでください。
- 実装、テスト、レビュー、GitHub操作、証跡作成はCLIを第一選択にしてください。GUI／Desktop clientが受入条件に明記されていない限り、GUI操作をテストの前提にしないでください。GUIが明記されていても、ユーザーの明示許可なしに実行せず、CLIで代替した場合は証跡へ明記してください。
- 並列agentが完了したら結果とworktreeのclean／未push状態を確認し、不要なagentとmerge済みworktreeを整理してください。引き継ぎ資料はagentの判断、checkpoint、review、merge、Issue状態を随時更新してください。

## GitHub Issue/PR Markdown integrity policy

- IssueとPRのタイトル、本文、コメント、レビュー本文は、GitHub上で正しく描画される実Markdownとして作成してください。CLIから送信する本文は実改行を持つbody fileまたは同等の入力を使い、文字列中のリテラル`\n`、エスケープ済みコードフェンス、不要なシェル引用符をそのまま送信しないでください。
- 見出し、箇条書き、コードフェンス、表、引用、段落の間には必要な空行を入れ、コードフェンスは開始と終了を対応させてください。バッククォート、リンク、チェックボックスの構文が本文中で壊れていないことを確認してください。
- CLIでIssueまたはPRを作成・更新した直後に、GitHubから保存済み本文をCLIで再取得し、実改行、空行の配置・保持、コードフェンスの対応、リンク、チェックボックス、Issue／PR参照が保持されていることを確認してください。使用した再取得コマンドと確認結果を引き継ぎ資料へ記録し、崩れがあればレビュー依頼やmergeの前に修正して再確認してください。
- PR本文には対象Issue、依存Issue／PR、受入条件、実行した検証をMarkdownで明記し、Issue本文にも依存関係・並列可否・競合ファイル・必要なmerge順を同じくMarkdownで明記してください。
- 引き継ぎ資料には、Markdown検証を実施した対象、確認結果、修正履歴を記録してください。Markdownの見た目確認のために視覚captureをCIへ追加してはいけません。

## Issue/PR execution checklist

1. 作業開始後の最初の10分で、Issue、PR、依存関係、既存変更を棚卸ししてください。

2. Issueを「単純・独立」「共有ファイルあり」「受入条件不明」に分類し、分類結果と必須アクションをIssueへ記録してください。「単純・独立」は並列候補として進め、「共有ファイルあり」は並列編集を停止して依存PRとmerge順を固定し、「受入条件不明」は実装を停止して確認依頼またはblockerをIssueへ記録してください。

3. 「単純・独立」Issueから、1 Issue＝1専用worktree＝1 PRを維持し、write setが重ならない範囲でサブエージェントへboundedに並列委任してください。

4. 各agentの担当Issue、担当ファイル、変更範囲、受入条件、依存関係を作業開始時点で固定してください。共有ファイルやschemaが重なる場合は並列編集を止め、merge順をIssueへ記録してください。

5. 対象テストが通ったPRだけをレビューへ回し、各PRについて独立したCodex reviewを必ず依頼してください。独立とは、実装担当と異なるCodexセッションまたはレビュアーが、実装担当の未確定な推論に依存せず差分を確認することです。レビュー対象はpush済みの安定したexact head SHAに固定し、そのSHAをIssue、PR、引き継ぎ資料へ記録してください。

6. Codex reviewで指摘があれば、actionableな指摘は修正してテストを再実行し、修正後の同じPRの最新head SHAをCodexへ再レビュー依頼してください。false positiveまたは採用しない提案は、理由と判断をIssue／PRへ記録して明示的にdispositionし、該当review threadを解決してください。push前のreview、CI、thread状態を新しいheadの証跡として流用せず、未対応または未dispositionの指摘を残したままmergeしてはいけません。

7. 同一のPR head SHAに紐づくexact-headのCodex review、登録済みCIの成功、未解決review thread 0を確認し、確認したhead SHAを記録してからmergeしてください。`scripts/check_pr_merge_readiness.py`の結果も記録し、merge操作自体にもその検証済みSHAを固定してください。CLIなら`gh pr merge --match-head-commit <verified-sha>`、connector/APIならexpected head SHA相当を指定し、headが変わった場合はmergeを止めてreadinessからやり直してください。

8. merge直後にIssue、親Issue、専用worktreeの状態、local branchの状態、引き継ぎ資料を更新してください。production verificationが完了するまではIssue専用worktreeを保持し、検証後に未push変更・ユーザー所有変更・clean状態を確認してから、不要になったmerge済みworktreeとlocal branchを整理してください。

9. 最後に対象repo `Sunwood-ai-labs/NyankoFace`、確認時点、期待状態を固定して、open Issue数、open PR数、対象Issue／PRの状態、`git worktree list --porcelain`から動的に特定したmain worktreeの既存変更を確認し、結果を引き継ぎ資料へ記録してください。remote状態を確認する前に`git fetch origin main`を実行し、merge commitとremote `main` SHAを記録してください。そのうえで`git merge-base --is-ancestor <merge-commit> origin/main`または同等のCLI確認でmerge commitがremote `main`に含まれることを確認してください。後続の独立mergeがない場合だけremote `main`の先端SHAとの一致を期待し、後続commitがある場合は祖先関係を期待状態とします。merge直後の対象Issueがclosed、対象PRがmerged、main worktreeのユーザー所有変更が保持されていることも記録してください。
