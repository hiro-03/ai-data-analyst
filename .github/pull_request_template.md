## 概要

<!-- 変更内容を簡潔に -->

## Virtual CTO レビュー（.cursorrules セクション 5）

PR 作成時に以下を確認してください（該当なしは N/A）。

- [ ] **IAM**: `template.yaml` 等で不適切な `Resource: "*"` がない（README の既知例外を踏まえた）
- [ ] **Secrets 整合**: README / `deploy.yml` / `template.yaml` の変数名が一致している
- [ ] **SRP / Cognito**: モバイルは SRP、Web×stg のみパスワードフロー、本番 Web は SRP（`cognito_service.dart` / `template.yaml` と整合）
- [ ] **型の一貫性**: バックエンド Pydantic と Flutter モデル（API 契約）を更新している
- [ ] **日本語**: 新規コードのコメント・ドキュメント方針に沿っている

**機械チェック**: CI の `CI (test + lint + build)` が緑であること（pytest / mypy / SAM）。

<!-- レビュア向け: Actions の Job サマリーに Virtual CTO 手動チェックリストが表示されます -->
