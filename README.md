# 釣果予測 API（本番稼働グレード）

位置情報（緯度・経度）をもとに最寄りの観測所を解決し、
潮汐・海況・気象の3種データをリアルタイムで収集して、
**Amazon Bedrock AgentCore** による高精度な釣り推論アドバイスを返すサーバーレス API です。

本番運用に必要なセキュリティ・可観測性・耐障害性の要件を IaC（AWS SAM）で完全コード化しています。

---

## アーキテクチャ概要

```
クライアント
  │  POST /fishing（Cognito JWT 必須）
  ▼
WAFv2（レート制限 + AWS マネージドルール）
  │
API Gateway（REST API / アクセスログ・X-Ray トレース有効）
  │
Lambda：API プロキシ
  ├─ Pydantic による入力バリデーション
  ├─ trace_id（UUID）の発行
  └─ Step Functions Express を同期実行
       │
       ├─【Parallel】─ GetTide（Stormglass / DynamoDB キャッシュ）
       │               GetMarine（Open-Meteo Marine / DynamoDB キャッシュ）
       │               GetForecast（気象庁 JMA API / DynamoDB キャッシュ）
       │               ※ いずれか失敗しても Catch で推論を継続（部分障害許容設計）
       │
       └─ FishingInferenceLambda
            ├─ Bedrock AgentCore（InvokeAgent）呼び出し
            ├─ Pydantic による出力スキーマ検証（非 JSON・範囲外値は即例外）
            └─ CloudWatch カスタムメトリクス（AdviceScore）送信
```

**主要 AWS サービス構成**

| レイヤー | サービス | 役割 |
|---------|---------|------|
| セキュリティ | Cognito / WAFv2 | JWT 認証・レート制限・マネージドルール |
| 計算 | Lambda（Python 3.11）/ Step Functions Express | 推論オーケストレーション |
| ストレージ | DynamoDB（2テーブル）| 観測所マスタ・外部 API キャッシュ（TTL + PITR）|
| 可観測性 | CloudWatch Alarms / X-Ray / SNS | ドリフト検知・分散トレース・アラート通知 |
| CI/CD | GitHub Actions / AWS SAM | OIDC 認証・stg E2E ゲート・prod 手動承認 |

---

## セキュリティ設計方針

- **最小権限の原則**: GitHub Actions デプロイロールの IAM ポリシーは、各サービスをプロジェクト名プレフィックス（`ai-data-analyst-fishing*`）でスコープ。`Resource: "*"` が残る箇所（X-Ray・ログ配信 API）は AWS サービス制約に起因するため、`scripts/deploy-extra-policy.json` にコメントで明記済み。
- **OIDC 認証**: 長期 IAM キーを使用せず、GitHub Actions から一時クレデンシャルで AWS 操作。ロールは stg（`AWS_ROLE_ARN_STG`）と prod（`AWS_ROLE_ARN_PROD`）で分離。
- **環境分離**: `Stage` パラメータ（`stg` / `prod`）が DynamoDB の削除保護・Cognito 認証フロー・SFN 実行データのロギング・API Gateway ステージ名・CloudWatch アラームメトリクスを一括制御。
- **Pydantic バリデーション**: API 入口（リクエスト）と推論出口（Bedrock レスポンス）の両方でスキーマ検証。Bedrock が非 JSON・範囲外値を返した場合は即 `ValidationError` → SFN が `FAILED` となり、サイレント劣化を防止。
- **Cognito 強化設定**:
  - `AllowAdminCreateUserOnly: true`（自己登録禁止）
  - `PreventUserExistenceErrors: ENABLED`（ユーザー存在の類推を防止）
  - `ALLOW_ADMIN_USER_PASSWORD_AUTH` は staging 環境のみ有効（`IsNotProd` 条件）。本番は SRP 専用。

---

## CI/CD パイプライン

```
push to main
    │
    ▼
[Job 1] CI ゲート（AWS 認証不要）
    ├─ pytest（カバレッジ 80% 未満で失敗）
    ├─ mypy strict モード（型チェック）
    ├─ sam validate --lint
    └─ sam build
    │
    ▼
[Job 2] stg デプロイ（staging ロール・自動）
    │
    ▼
[Job 3] E2E スモークテスト（staging 環境）
    ├─ CloudFormation Outputs から API URL・Cognito 情報を自動取得
    ├─ Cognito 認証 → JWT 取得
    └─ POST /fishing エンドポイントの疎通確認
    │   ↑ 失敗時はここで停止（本番には触れない）
    ▼
[Job 4] prod デプロイ（production ロール・手動承認必須）
    └─ GitHub Environments の Required reviewers による承認ゲート
```

---

## デプロイ手順

### 事前準備：GitHub Actions OIDC セットアップ（初回のみ）

長期 IAM キーを発行せず、OIDC フェデレーションで一時クレデンシャルを使用します。

```bash
# 1. OIDC プロバイダーをアカウントに登録（1アカウントにつき1回）
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. IAM ロールを作成し、trust policy を適用
#    - trust policy: scripts/github-actions-trust-policy.json
#    - 追加 inline ポリシー: scripts/deploy-extra-policy.json

# 3. GitHub リポジトリの Secrets に以下を登録
#    AWS_ROLE_ARN_STG  = arn:aws:iam::<ACCOUNT_ID>:role/github-actions-ai-data-analyst
#    AWS_ROLE_ARN_PROD = arn:aws:iam::<ACCOUNT_ID>:role/github-actions-ai-data-analyst
#    ALARM_EMAIL       = 通知先メールアドレス

# 4. GitHub Environments を設定
#    Settings → Environments → staging
#      Secrets: STG_SMOKE_USER_EMAIL / STG_SMOKE_USER_PASSWORD
#    Settings → Environments → production
#      Required reviewers: 承認者を追加（手動承認ゲート）
```

### ローカルからの手動デプロイ

```powershell
sam validate --template-file template.yaml --lint
sam build

# staging
sam deploy --config-env stg `
  --parameter-overrides AlarmEmail="stg-alert@example.com" Stage="stg"

# production
sam deploy --config-env default `
  --parameter-overrides `
    AlarmEmail="prod-alert@example.com" `
    BedrockAgentArn="arn:aws:bedrock:ap-northeast-1:123456789012:agent/AGENTID" `
    Stage="prod"
```

---

## 外部 API キー管理（SSM Parameter Store）

APIキーは環境変数に直書きせず、SSM Parameter Store（SecureString）で管理します。

```bash
# Stormglass（潮汐データ）
aws ssm put-parameter \
  --name "/ai-data-analyst/external/stormglass/api-key" \
  --type "SecureString" \
  --value "<YOUR_API_KEY>" \
  --overwrite
```

---

## 観測所マスタのシード投入

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\seed_stations.ps1 `
  -StackName ai-data-analyst-fishing `
  -Region ap-northeast-1
```

---

## Cognito 認証

デプロイ完了後、CloudFormation Outputs に `CognitoUserPoolId` と `CognitoUserPoolClientId` が出力されます。

> **認証フロー設計**  
> - 本番: `ALLOW_USER_SRP_AUTH` のみ有効。パスワードはクライアント側でハッシュ化され、平文では通信しない。  
> - staging: `ALLOW_ADMIN_USER_PASSWORD_AUTH` を追加許可。AWS IAM 認証が必要なため、IAM クレデンシャルなしでは使用できない。CI のスモークテストはこの認証フローを使用する。

### 1. テストユーザーの作成

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username "demo@example.com" \
  --user-attributes Name=email,Value=demo@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS

aws cognito-idp admin-set-user-password \
  --user-pool-id <USER_POOL_ID> \
  --username "demo@example.com" \
  --password "<12文字以上・大文字・数字・記号を含むパスワード>" \
  --permanent
```

### 2. ID トークンの取得

`ADMIN_USER_PASSWORD_AUTH` は呼び出し元に AWS IAM 認証を要求します（パスワード単体では使用不可）。

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id <USER_POOL_ID> \
  --client-id <APP_CLIENT_ID> \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME="demo@example.com",PASSWORD="<STRONG_PASSWORD>"
```

レスポンスの `AuthenticationResult.IdToken` を API 呼び出しに使用します。

---

## API 呼び出し例

```powershell
$token = "<ID_TOKEN>"
curl.exe -s -X POST `
  "https://<restApiId>.execute-api.ap-northeast-1.amazonaws.com/<stage>/fishing" `
  -H "Content-Type: application/json" `
  -H "Authorization: $token" `
  -d '{"lat":35.681236,"lon":139.767125,"target_species":"ajing","spot_type":"harbor"}'
```

`scripts/test_api.ps1` を使うと、CloudFormation Outputs から URL を自動取得し、Cognito 認証まで含めて一括実行できます。

```powershell
.\scripts\test_api.ps1 -StackName ai-data-analyst-fishing
```

---

## データ収集仕様

### 気象予報（気象庁 JMA API）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `https://www.jma.go.jp/bosai/forecast/data/forecast/{officeCode}.json` |
| キャッシュキー | `forecast:jma:<office_code>:<YYYY-MM-DD>` |
| TTL | +2日 |
| 備考 | 緯度・経度から最寄りの気象台コードを自動解決（47都市対応）|

### 潮汐（Stormglass）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `GET /v2/tide/extremes` |
| キャッシュキー | `tide:stormglass:<lat>:<lon>:<YYYY-MM-DD>` |
| TTL | +2日 |

### 海況（Open-Meteo Marine）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `https://marine-api.open-meteo.com/v1/marine` |
| 取得変数 | 海面水温・波高・波向・周期 |
| キャッシュキー | `marine:openmeteo:<lat>:<lon>:<YYYY-MM-DDTHH>` |
| TTL | +3時間（気象変化を反映するため短め）|

### 部分障害時の挙動

Step Functions の並列ステートに `Catch` を設定しているため、潮汐・海況・気象のいずれかの取得が失敗しても **推論ステップは継続**します。取得できたデータのみで推論し、欠損は推論結果の `evidence` フィールドに反映されます。

---

## 監視・運用

### アラート通知

`template.yaml` の SNS サブスクリプション（メール）が自動作成されます。  
**初回デプロイ後、登録したメールアドレスに届く確認メールの承認が必要です。**

| アラーム名 | 条件 | 目的 |
|-----------|------|------|
| `FishingApi5xxAlarm` | 5xx エラー 5分中3分以上 | API Gateway レベルの障害検知 |
| `FishingApiProxyErrorsAlarm` | Lambda エラー 5分中3分以上 | プロキシ Lambda の異常検知 |
| `InferenceScoreAbsoluteAlarm` | スコア平均 < 50 が2時間継続 | 推論品質の壊滅的劣化を検知 |
| `InferenceScoreDriftRatioAlarm` | スコア平均 < 45 が24時間中16時間 | 推論品質の緩やかな劣化を検知 |

### ログ出力先

| ログ種別 | 出力先（CloudWatch Logs） |
|---------|------------------------|
| API Gateway アクセスログ | `/aws/apigateway/<stack>/<stage>/access` |
| Step Functions 実行ログ | `/aws/stepfunctions/<stack>/FishingAdviceStateMachine` |
| Lambda 関数ログ | `/aws/lambda/<function-name>` |

> 本番環境（`Stage=prod`）では Step Functions の実行データ（入出力）を **ログに記録しません**。  
> 外部 API レスポンスに含まれる API キーや個人に紐づく位置情報の CloudWatch への流出を防ぐためです。  
> staging では全実行データをログ出力し、デバッグを容易にしています。

---

## ローカル動作確認

```bash
# Bedrock なしでレスポンス形式のみ確認する場合
INFERENCE_PROVIDER=mock python lambdas/fishing/infer/lambda_function.py

# 単体テスト（カバレッジレポート付き）
pytest tests/ --cov=lambdas --cov=layers --cov-report=term-missing

# 型検査
mypy layers/fishing_common/python/fishing_common/ lambdas/ \
  --ignore-missing-imports --explicit-package-bases
```
