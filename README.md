# Fishing Advice API (Production-ready baseline)

このプロジェクトは、位置情報（lat/lon）から **最寄り観測所**を解決し、
- **潮汐（Stormglass）**
- **海況（Open-Meteo Marine）**
- **天気予報（JMA）**
- **季節/月**
を収集して、（任意で）**Amazon Bedrock AgentCore** による釣り推論結果を返す API です。

本番運用の最小要件として、
- **Cognito（ログイン必須）**
- **WAF（レート制限＋Managed Rules）**
- **API Gateway Access Logs**
- **CloudWatch Alarms → SNS Email 通知**
- **外部APIのリトライ/バックオフ**
- **DynamoDB PITR**
を組み込んでいます。

## 🏗 Architecture
- API Gateway (REST API): `POST /fishing`（Cognito JWT必須）
- Lambda (API Proxy): 入力検証・trace_id付与・Step Functions（Express）同期実行
- Step Functions (Express): `GetTide` / `GetMarine` / `GetForecast` を並列取得（失敗しても推論継続）→ 推論
- DynamoDB:
  - `StationsTable`: 観測所マスタ
  - `ExternalApiCacheTable`: 外部API結果のTTLキャッシュ（+ PITR）
- CloudWatch:
  - API Gateway Access Logs
  - Lambda / SFN ログ
  - アラーム（SNS Email通知）

## 🚀 Deploy

```powershell
sam validate --template-file template.yaml --lint
sam build
sam deploy --stack-name "ai-data-analyst-fishing" `
  --s3-prefix "ai-data-analyst-fishing" `
  --resolve-s3 --region ap-northeast-1 `
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
  --parameter-overrides AlarmEmail="your@email.com" BedrockAgentArn="arn:aws:bedrock:ap-northeast-1:123456789012:agent/ABCDEF"
```

## 🔒 GitHub Actions OIDC Setup (one-time)

長期 IAM キーを使わず、OIDC フェデレーションによる一時クレデンシャルで CI を動かします。

```bash
# 1. OIDC プロバイダー作成（アカウントに1つあれば OK）
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. IAM ロール「github-actions-ai-data-analyst」を作成し、
#    trust policy で repo:<ORG>/<REPO>:ref:refs/heads/main のみ許可。
#    デプロイに必要なポリシーを attach する。

# 3. GitHub Secrets に追加:
#    AWS_ROLE_ARN  = arn:aws:iam::<ACCOUNT_ID>:role/github-actions-ai-data-analyst
#    ALARM_EMAIL   = your@email.com
```

## 🔑 External API Keys (SSM Parameter Store)

### Stormglass
- **SSM parameter**: `/ai-data-analyst/external/stormglass/api-key`（SecureString推奨）

```bash
aws ssm put-parameter \
  --name "/ai-data-analyst/external/stormglass/api-key" \
  --type "SecureString" \
  --value "<YOUR_API_KEY>" \
  --overwrite
```

## 🌱 Seed Stations

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_stations.ps1 -StackName ai-data-analyst-fishing -Region ap-northeast-1
```

## 🔐 Auth (Cognito) - API実行に必要

デプロイ後、CloudFormation Outputs に `CognitoUserPoolId` と `CognitoUserPoolClientId` が出ます。

> **設計方針**: アプリクライアントは `ALLOW_USER_SRP_AUTH`（パスワードをクライアント側でハッシュ化）のみを許可。
> CLI テスト用に `ALLOW_ADMIN_USER_PASSWORD_AUTH` を有効化（AWS IAM 認証が必要なため、パスワード単体では使えない）。

### 1) ユーザー作成（管理者作成）

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username "demo@example.com" \
  --user-attributes Name=email,Value=demo@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS
```

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id <USER_POOL_ID> \
  --username "demo@example.com" \
  --password "<STRONG_PASSWORD_12chars+Upper+Num+Symbol>" \
  --permanent
```

### 2) トークン取得（管理者 API フロー）

`admin-initiate-auth` は AWS IAM 認証を必要とするため、平文パスワードのみでの認証より安全です。

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id <USER_POOL_ID> \
  --client-id <APP_CLIENT_ID> \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME="demo@example.com",PASSWORD="<STRONG_PASSWORD>"
```

レスポンスの `AuthenticationResult.IdToken` を控えます。

## 📡 Call API

```powershell
$token = "<ID_TOKEN>"
curl.exe -s -D - -X POST "https://<restApiId>.execute-api.ap-northeast-1.amazonaws.com/prod/fishing" `
  -H "Content-Type: application/json" `
  -H "Authorization: $token" `
  -d '{"lat":35.681236,"lon":139.767125,"target_species":"ajing","spot_type":"harbor"}'
```

## 🧠 Data collection details

### Forecast (JMA)
- Endpoint: `https://www.jma.go.jp/bosai/forecast/data/forecast/{officeCode}.json`
- Cache key（概念）: `forecast:jma:<office_code>:<YYYY-MM-DD>`
- TTL: おおむね **+2日**

### Tide (Stormglass)
- Endpoint: `GET /v2/tide/extremes`
- Cache key（概念）: `tide:stormglass:<lat_round>:<lon_round>:<YYYY-MM-DD>`
- TTL: おおむね **+2日**

### Marine (Open-Meteo Marine)
- Endpoint: `https://marine-api.open-meteo.com/v1/marine`
- Variables: `sea_surface_temperature`, `wave_height`, `wave_direction`, `wave_period`
- Cache key（概念）: `marine:openmeteo:<lat_round>:<lon_round>:<YYYY-MM-DDTHH>`
- TTL: おおむね **+3日**

### Partial failure behavior
- Step Functions の並列取得は `Catch` を入れているため、潮汐/海況/予報の一部が失敗しても **推論は継続**します。

## 🚨 Ops / Monitoring

### SNS Email 通知
- `template.yaml` で SNS サブスクリプション（email）を作成しています。
- **初回はメールで届く Confirm を承認する必要があります**。

### Logs
- **API Gateway access logs**: `/aws/apigateway/<stack>/prod/access`
- **Step Functions logs**: `/aws/stepfunctions/<stack>/FishingAdviceStateMachine`
- **Lambda logs**: `/aws/lambda/<function-name>`

## 🧪 Notes
- `INFERENCE_PROVIDER=mock` の場合、Bedrockなしでレスポンス形だけ確認できます。

---

## 🤖 AI-Native Development — 生成AIと築く本番品質

本プロジェクトは、生成AI（Cursor / Claude）を「コード補完ツール」ではなく **バーチャルなリードエンジニア兼アーキテクト** として活用し、個人開発でありながらチーム開発に匹敵する品質基準を達成しています。

### 開発スタイル：AIペアプログラミング

Cursor 上で Claude とのリアルタイム対話を通じ、設計・実装・レビュー・是正を一気通貫で行いました。
従来の「書いてからレビューに出す」ワークフローではなく、**設計意図を自然言語で伝え、生成されたコードをその場で検証・修正するライブセッション型** の開発プロセスです。

具体例:
- Step Functions の状態遷移定義（Parallel + Catch フォールバック）を対話的に設計し、外部API障害時にも推論を継続する部分障害耐性を実現
- IAM ポリシーの最小権限設計（Lambda ごとにリソースARNをスコープ、CloudWatch `PutMetricData` に namespace 条件を付与）をレビューサイクルの中で段階的に引き締め
- Pydantic スキーマをAPI入力と推論出力の双方に適用する「Contract-First」設計を、型安全性の観点から議論しながら確定

### 激辛レビューサイクル：複数AIペルソナによる多角的検証

開発の各フェーズで、AIに **異なる専門家ペルソナ** を設定し、3回以上の徹底的なレビューと是正を繰り返しました。

| ペルソナ | 検証観点 | 指摘・是正の例 |
|---|---|---|
| **MLOps リードエンジニア** | 推論パイプラインの信頼性・可観測性 | Bedrock 推論スコアの CloudWatch カスタムメトリクス追加、スコアドリフト検知アラーム設計 |
| **メガベンチャー CTO** | セキュリティ・運用・スケーラビリティ | OIDC フェデレーション導入（長期IAMキー廃止）、WAF レート制限 + マネージドルール適用 |
| **シニア SRE** | 障害耐性・デプロイ安全性 | ステージング→スモークテスト→本番の段階デプロイ、DynamoDB PITR 有効化 |

最終的に **Sランク判定**（シニアエンジニアの要求水準をクリア）に到達するまで、設計の甘さやエッジケースを徹底的に潰しました。

### 到達した品質水準

**セキュリティ**
- GitHub Actions OIDC 認証（長期クレデンシャルゼロ）
- Cognito JWT 認証 + 本番環境では `ADMIN_USER_PASSWORD_AUTH` を無効化
- IAM ポリシーを Lambda 関数単位でリソーススコープ
- WAF（IP レート制限 500req/5min + AWSManagedRulesCommonRuleSet）

**堅牢性**
- 外部API呼び出しに指数バックオフ付きリトライ（429/5xx を最大3回）
- Step Functions Parallel の各ブランチに Catch → Pass フォールバック（部分障害でも推論継続）
- DynamoDB TTL キャッシュによる外部API依存の軽減

**データ品質**
- Pydantic v2 による入出力の厳密なバリデーション（`FishingRequest` / `FishingAdviceResponse`）
- mypy strict モードによる静的型検査
- pytest 78テスト、カバレッジ 80% 以上をCI必須ゲートとして設定

**CI/CD**
- 4段階パイプライン: CI → Staging Deploy → Smoke Test → Production Deploy
- SAM validate + lint、mypy、pytest をすべてパスしないとデプロイ不可
- 本番デプロイ前にステージング環境でのE2Eスモークテストをゲートとして設置

### 意図的な設計判断：AIの提案を鵜呑みにしない

AIの出力をそのまま採用するのではなく、**設計判断の根拠を自ら検証し、取捨選択** しています。

- **DynamoDB キャッシュの設計**: AIが提案した複合キー構造に対し、TTL ベースの単一テーブル設計を選択。理由は、外部APIレスポンスのキャッシュという用途では、パーティションキーの均等分散よりも TTL による自動パージと運用のシンプルさを優先すべきと判断
- **Express vs Standard Step Functions**: 同期APIレスポンスが要件であるため、AIが示した Standard ワークフロー案ではなく Express を採用し、API Gateway からの直接同期呼び出しを実現
- **スモークテストの設計**: Cognito 認証を含むフルE2Eテストとしつつ、Secrets 未設定時はグレースフルスキップする設計で、CI パイプラインの可搬性を確保

### このアプローチが示すもの

生成AIは「コードを書かせるツール」ではなく、**設計の壁打ち相手であり、多角的なレビュアーであり、ベストプラクティスの引き出し** です。
重要なのは、AIの出力を評価・判断し、最終的な設計責任を開発者自身が持つこと。
このプロジェクトは、そのプロセスを通じて **個人開発でもプロダクション品質に到達できる** ことを実証しています。

