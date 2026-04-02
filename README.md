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
#    trust policy (scripts/github-actions-trust-policy.json) を適用。
#    デプロイに必要なポリシーを attach し、inline ポリシーとして
#    scripts/deploy-extra-policy.json を追加する。

# 3. GitHub Secrets に追加（stg / prod でロールを分離）:
#    AWS_ROLE_ARN_STG  = arn:aws:iam::<ACCOUNT_ID>:role/github-actions-ai-data-analyst
#    AWS_ROLE_ARN_PROD = arn:aws:iam::<ACCOUNT_ID>:role/github-actions-ai-data-analyst
#    ALARM_EMAIL       = your@email.com
#
# 4. GitHub Environments を設定:
#    Settings → Environments → staging  : Secrets に STG_SMOKE_USER_EMAIL / STG_SMOKE_USER_PASSWORD
#    Settings → Environments → production: Required reviewers を追加（手動承認ゲート）
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

