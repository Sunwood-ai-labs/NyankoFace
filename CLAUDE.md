# Claude project instructions

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
