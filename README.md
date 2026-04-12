# 釣り推論 API（本番運用品質）

クライアントから送られた **緯度・経度** に基づき **最寄りの観測所を特定**し、
潮汐・海況・気象の **3 系統**のデータを外部 API から取得したうえで、
**Amazon Bedrock のエージェント**（`bedrock-agent-runtime` の **`InvokeAgent`**）により釣りのアドバイスを返すサーバーレス API です。

本番運用に求められるセキュリティ・可観測性・耐障害性の要件を、IaC（AWS SAM）でコードとして定義しています。

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
            ├─ Amazon Bedrock エージェント（InvokeAgent）呼び出し
            ├─ Pydantic による出力スキーマ検証（非 JSON・範囲外の値はすぐに例外）
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

### 推論レイヤーと用語

- 推論は **Amazon Bedrock のエージェント**を **`bedrock-agent-runtime` の `InvokeAgent`** で呼び出します。エージェント ID・エイリアス ID は SSM（`/ai-data-analyst/bedrock/agent/*`）経由で Lambda に渡します。
- AWS が別途提供する **「Amazon Bedrock AgentCore」**（URL に `bedrock-agentcore` が含まれる専用ホームのレジストリ／ランタイム等）は **本リポジトリのコードパスとは別製品**です。セットアップは **メインの Amazon Bedrock**（モデルアクセス・エージェントの作成）から行ってください。

---

## セキュリティ設計方針

- **最小権限の原則**: GitHub Actions 用デプロイロール（`scripts/deploy-extra-policy.json`）は **`Resource: "*"` を使用しない**。各リソースはアカウント・プレフィックスまたは **stg/prod の API Gateway RestApi ID** で固定した ARN に限定する。Bedrock の `GetAgent` 等は **デプロイ時に GitHub ロール経由で呼ばれない**ため本ポリシーから除外している（運用で必要なら管理者ロールで実行）。Lambda 推論ロールの `cloudwatch:PutMetricData` のみ、AWS 仕様上 `Resource: "*"` と `cloudwatch:namespace` 条件の組み合わせが必要（カスタムメトリクスはリソース ARN を指定できない）。
- **ARN 末尾のプレフィックスワイルドカード（`*`）**: `deploy-extra-policy.json` では、アラーム名・SNS・ロググループ・SSM パスなど **リソース名の共通プレフィックスに続く部分**を `ai-data-analyst-fishing*` のように許容する。これは **サービス全体への無制限 `Resource:*` とは別**であり、スタック名プレフィックスでスコープした命名に合わせるためのものである。
- **`infra/*.json` は参照用サンプル**: `Resource: "*"` を含む過去のドラフトが残っている。**運用で attach するインラインポリシーは `scripts/deploy-extra-policy.json` を正とする**（理由と注意は `infra/README.md`）。
- **`template.yaml` の `BedrockAgentArn` 既定値**: 単独の `"*"` は使わず、`arn:aws:bedrock:ap-northeast-1:476963918877:agent/*` と **当アカウント内の Bedrock エージェント ARN パターンにのみ**スコープする。本番では `BEDROCK_AGENT_ARN` などで特定エージェント ID の ARN を渡すことを推奨。
- **API Gateway `MethodSettings` の `HttpMethod: "*"` / `ResourcePath: "/*"`**: これらは **IAM の Resource ではなく**、ステージにどのメソッド・パスへログ設定を適用するかの CloudFormation プロパティである。
- **OIDC 認証**: 長期の IAM アクセスキーを置かず、GitHub Actions から一時クレデンシャルで AWS を操作します。ロールは stg（`AWS_ROLE_ARN_STG`）と prod（`AWS_ROLE_ARN_PROD`）で分けています。
- **環境分離**: `Stage` パラメータ（`stg` / `prod`）により、DynamoDB の削除保護、Cognito の認証フロー、Step Functions の実行データのログ記録の有無、API Gateway のステージ名、CloudWatch アラームのディメンションなどを **環境ごとに切り替え**ます。
- **Pydantic バリデーション**: API の入口（リクエスト）と推論の出口（Bedrock レスポンス）の **両方**でスキーマ検証します。Bedrock が非 JSON や範囲外の値を返した場合は `ValidationError` とし、Step Functions の実行は `FAILED` になります。推論結果の **見かけ上の成功による品質劣化**を防ぎます。
- **Cognito 強化設定**:
  - `AllowAdminCreateUserOnly: true`（自己登録禁止）
  - `PreventUserExistenceErrors: ENABLED`（ユーザー列挙攻撃の抑止）
  - `ALLOW_USER_PASSWORD_AUTH` / `ALLOW_ADMIN_USER_PASSWORD_AUTH` は staging のみ（`IsNotProd`）。**モバイル・デスクトップは SRP**、**Flutter Web（stg）は開発利便のため `USER_PASSWORD_AUTH` 可**。

---

## CI/CD パイプライン

```
push to main
    │
    ▼
[Job 1] CI ゲート（AWS 認証不要）
    ├─ pytest（カバレッジ 80% 未満で失敗）
    ├─ mypy（型チェック）
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

# 3. GitHub Secrets（下表と deploy.yml の参照名を 1 文字もずらさないこと）
#    本ワークフローは AWS Secrets Manager を直接参照しません（パラメータは GitHub Secrets のみ）。

# 4. GitHub Environments を設定
#    Settings → Environments → staging
#      Required reviewers: 任意（自動デプロイのままでも可）
#    Settings → Environments → production
#      Required reviewers: 承認者を追加（手動承認ゲート）
```

#### GitHub Secrets 管理表（`.github/workflows/deploy.yml` と完全一致）

変数名は **リポジトリ Secrets** と **Environment Secrets** のどちらでもよい（同名なら Environment が優先）。**AWS Secrets Manager は本パイプラインでは未使用**です。

| Secret 名 | 必須 | 用途 | `deploy.yml` 内の参照 |
|-----------|:----:|------|------------------------|
| `AWS_ROLE_ARN_STG` | ✅ | OIDC で引き受けるステージング用 IAM ロール ARN | `secrets.AWS_ROLE_ARN_STG` |
| `AWS_ROLE_ARN_PROD` | ✅ | 本番デプロイ用 IAM ロール ARN | `secrets.AWS_ROLE_ARN_PROD` |
| `ALARM_EMAIL_STG` | 任意 | stg のアラーム通知メール（未設定時はワークフロー内の既定値） | `secrets.ALARM_EMAIL_STG` |
| `BEDROCK_AGENT_ARN_STG` | 任意 | stg の Bedrock エージェント ARN（未設定時は `template.yaml` の `BedrockAgentArn` 既定と同じ `arn:aws:bedrock:ap-northeast-1:476963918877:agent/*` を `deploy.yml` が渡す） | `secrets.BEDROCK_AGENT_ARN_STG` |
| `STG_SMOKE_USER_EMAIL` | ✅（E2E ゲート利用時） | stg スモークテスト用 Cognito ユーザー名 | `secrets.STG_SMOKE_USER_EMAIL` |
| `STG_SMOKE_USER_PASSWORD` | ✅（E2E ゲート利用時） | 上記ユーザーのパスワード | `secrets.STG_SMOKE_USER_PASSWORD` |
| `ALARM_EMAIL` | 任意 | 本番アラーム通知メール | `secrets.ALARM_EMAIL` |
| `BEDROCK_AGENT_ARN` | 任意 | 本番 Bedrock エージェント ARN（未設定時は上記と同様に `agent/*` 既定を渡す） | `secrets.BEDROCK_AGENT_ARN` |

### ローカルからの手動デプロイ

`sam deploy --parameter-overrides` に渡すキーは **CloudFormation のパラメータ名**であり、GitHub Secrets 名（例: `ALARM_EMAIL`）とは別である（対応関係は下表）。

| パラメータ名（`template.yaml`） | 主な用途 |
|--------------------------------|----------|
| `DeployTimestamp` | API デプロイの強制更新用（CI は `github.sha` を渡す想定） |
| `Stage` | `stg` または `prod` |
| `WafRateLimitPer5Min` | WAF レート制限（5 分あたり） |
| `ApiAccessLogRetentionDays` | API アクセスログの保持日数 |
| `AlarmEmail` | CloudWatch アラーム通知先（GitHub の `ALARM_EMAIL` / `ALARM_EMAIL_STG` と対応） |
| `BedrockAgentArn` | InvokeAgent の IAM スコープ（GitHub の `BEDROCK_AGENT_ARN` / `BEDROCK_AGENT_ARN_STG` と対応） |

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

API キーは環境変数に直書きせず、SSM Parameter Store（SecureString）で管理します。

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

> **認証フロー設計（ドキュメント・IaC・実装の三位一体）**
>
> | フロー | 利用主体 | 本番 | staging | 備考 |
> |--------|---------|:----:|:-------:|------|
> | **`USER_SRP_AUTH`（SRP）** | **Flutter モバイル・Windows（Amplify Auth）** | ✅ | ✅ | 平文パスワードをネットワークに載せない。 |
> | **`USER_PASSWORD_AUTH`** | **Flutter Web × stg**（ブラウザ向けフォールバック） | ❌ | ✅ | ブラウザでは SRP が不安定な場合があるため **ステージングのみ** HTTPS で許可。 |
> | `ADMIN_USER_PASSWORD_AUTH` | CI の `scripts/smoke_test.py` のみ | ❌ | ✅ | **AWS IAM** が必要。 |
>
> > **補足**: 本番のユーザープールクライアントには `USER_PASSWORD_AUTH` を含めない。CLI 検証は `admin-initiate-auth` または CI の ADMIN フローを使用する。

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
  -d '{"lat":35.681236,"lon":139.767125,"target_species":"aji","spot_type":"harbor"}'
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
| 備考 | 緯度・経度から最寄りの気象台コードを自動で特定（47 地点分のマッピング）|

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

Step Functions の並列ステートに `Catch` があるため、潮汐・海況・気象の **いずれかの取得に失敗しても推論ステップは続行**します。取得できたデータだけを使って推論し、欠けた情報は結果の `evidence` に反映されます。

---

## 監視・運用

### アラート通知

`template.yaml` の SNS サブスクリプション（メール）が自動作成されます。  
**初回デプロイ後、登録したメールアドレスに届く確認メールの承認が必要です。**

| アラーム名 | 条件 | 目的 |
|-----------|------|------|
| `FishingApi5xxAlarm` | 1 分ごとの評価を 5 回行い、そのうち 3 回以上で 5xx ≥1 | API Gateway 層の障害検知 |
| `FishingApiProxyErrorsAlarm` | 同上の評価パターンで Lambda エラー ≥1 | API プロキシ Lambda の異常検知 |
| `InferenceScoreAbsoluteAlarm` | 1 時間平均スコアが 50 未満の状態が 2 時間連続 | 推論品質の急激な低下を検知 |
| `InferenceScoreDriftRatioAlarm` | 1 時間平均が 45 未満の回数が、24 時間のうち 16 回以上 | 推論品質の緩やかな劣化を検知 |

### ログ出力先

| ログ種別 | 出力先（CloudWatch Logs） |
|---------|------------------------|
| API Gateway アクセスログ | `/aws/apigateway/<stack>/<stage>/access` |
| Step Functions 実行ログ | `/aws/stepfunctions/<stack>/FishingAdviceStateMachine` |
| Lambda 関数ログ | `/aws/lambda/<function-name>` |

### HTTP 502（Bad Gateway）が出るとき

API プロキシ Lambda は Step Functions の **同期実行**（`StartSyncExecution`）が `SUCCEEDED` 以外のとき **502**（タイムアウト時は **504**）を返します。レスポンス JSON には `error` に状態名、`cause` に **失敗理由（スタックトレースや Lambda エラー本文）** が入る。Flutter アプリのエラー表示にも `cause` と `trace_id` を含める。

**よくある原因の切り分け**

| 想定 | 確認先 |
|------|--------|
| 最寄り気象台解決に失敗（DynamoDB 空・権限） | `*-resolve_nearest_station` のログ、`STATIONS_TABLE` |
| Bedrock `InvokeAgent` 失敗・SSM のエージェント ID 不一致 | `*-fishing_infer` のログ、`/ai-data-analyst/bedrock/agent/*` |
| エージェントが JSON 以外を返す・スキーマ不一致 | 同上ログ（`ValueError` / `ValidationError`） |
| 実行が長すぎて API 側がタイムアウト | 504 に近い挙動。外部 API 遅延・推論レイテンシを確認 |

**`cause` に `accessDeniedException` / `Access denied when calling Bedrock` が含まれるとき**

Lambda からの `InvokeAgent` が IAM またはアカウント側設定で拒否されています。次を順に確認する。

| 確認 | 内容 |
|------|------|
| 推論 Lambda の IAM | ロールに `bedrock:InvokeAgent` が **`agent`・`agent-alias` の ARN**（SSM の ID と一致）に付いているか。テンプレート更新後は **再デプロイ**が必要。 |
| Bedrock のモデルアクセス | コンソール **Bedrock → Model access** で、エージェントが使う **基盤モデル（例: Anthropic Claude）** が **東京リージョンでアクセス許可**されているか。未承認・失効すると同種のエラーになることがある。 |
| エージェント側の実行ロール | エージェント設定の **Execution role** に、ナレッジベース・モデル呼び出しに必要な権限があるか（Lambda ロールとは別）。 |
| エージェントの再準備 | 設定変更後、コンソールでエージェントを **Save → Prepare**し、**エイリアス**を最新の準備済みバージョンに紐づけ直す。内部設定が古いと挙動がおかしくなることがある。 |

> 本番（`Stage=prod`）では、Step Functions の実行データ（入出力）を **CloudWatch Logs に残しません**。  
> 外部 API のレスポンスに含まれるキーや、位置情報などがログに流れないようにするためです。  
> staging では実行データをログに残し、障害調査しやすくしています。

---

## ローカル動作確認

```bash
# Bedrock なしでレスポンス形式のみ確認する場合
INFERENCE_PROVIDER=mock python lambdas/fishing/infer/lambda_function.py

# 単体テスト（カバレッジレポート付き）
pytest tests/ --cov=lambdas --cov=layers --cov-report=term-missing

# 型検査
mypy layers/fishing_common/fishing_common/ lambdas/ \
  --ignore-missing-imports --explicit-package-bases
```

### Virtual CTO 機械ゲート（コミット毎）

`pip install -r requirements-dev.txt` のあと **pre-commit を有効化**すると、`git commit` 時に `scripts/virtual_cto_gate.py --fast` が **pytest + mypy** を実行し、失敗時はコミットが拒否されます（緊急時のみ `git commit --no-verify`）。

```bash
pre-commit install
# 手動で全ファイルに対して実行する場合
pre-commit run --all-files
```

**GitHub 上の見える化**: `main` へ push した CI ジョブの **Summary** に、手動レビュー用チェックリスト（IAM・Secrets・型・日本語）が Markdown で追記されます。PR 作成時は `.github/pull_request_template.md` のチェックボックスも利用してください。

---

## 最終是正完了報告（CTO への回答）

最終ゲートで指摘された **3 点**について、コードとドキュメントで次のとおり完了した。

1. **IAM の厳格化**  
   `scripts/deploy-extra-policy.json` は **`Resource: "*"` を使用しない**。WAF と API Gateway ステージの関連付けは **`restapis/2ie0f0ucei/stages/*`（stg）と `restapis/kgiv7wxd8l/stages/*`（prod）** に限定（スタック再作成で RestApi ID が変わった場合は本ポリシーを更新）。不要だった Bedrock 読み取り Statement は **デプロイ経路で未使用のため削除**。  
   `template.yaml` の `BedrockAgentArn` パラメータ既定は **単独の `"*"` を廃止**し、当アカウントの `agent/*` パターンに変更。  
   併せて Step Functions 実行ロールのログ配信は **`SfnLogGroup` の ARN と `${LogGroupArn}:*`** に限定済み。  
   `FishingInferenceLambda` の `cloudwatch:PutMetricData` は **AWS 仕様上 `Resource: "*"` + `cloudwatch:namespace` 条件**のまま（カスタムメトリクスにリソース ARN を指定できない）。

2. **README と CI/CD の Secrets 完全同期**  
   **「GitHub Secrets 管理表」** の Secret 名と `.github/workflows/deploy.yml` の `secrets.*` およびファイル先頭コメントの列挙を **同一**に保つ。`BEDROCK_AGENT_*` 未設定時に渡す `BedrockAgentArn` のプレースホルダは **`template.yaml` の既定値と一致**させた。

3. **モバイル SRP 認証の整合**  
   **IaC**: `CognitoUserPoolClient` は常に `ALLOW_USER_SRP_AUTH`。`ALLOW_USER_PASSWORD_AUTH` / `ALLOW_ADMIN_USER_PASSWORD_AUTH` は **`IsNotProd`（stg）のみ**有効（本番は SRP のみ）。  
   **Flutter**: `AppConfig.usePasswordAuthOnWeb` は `kIsWeb && fishingApiUrl.contains('/stg/')` のため **モバイル／デスクトップは常に Amplify の SRP**。**Flutter Web かつ stg API URL** のときのみ `USER_PASSWORD_AUTH`（HTTPS）。  
   **CI**: `scripts/smoke_test.py` は **`ADMIN_USER_PASSWORD_AUTH`** でトークン取得（別経路）。

---

## CTO レビュー指摘事項と是正記録

本プロジェクトは外部 CTO 視点による厳格なコードレビューを受け、以下の指摘を是正した記録を誠実に開示します。

### 致命的 (Fatal)

| # | 指摘内容 | 是正内容 | 対象ファイル |
|---|---------|---------|-------------|
| 1 | `deploy-extra-policy.json` に広いリソース指定が残存 | `Resource: "*"` は使用しない。WAF–API Gateway の関連付けは stg/prod の RestApi ID で固定。Bedrock 読み取りはデプロイ不要のため削除。Step Functions ロールのログ権限は `SfnLogGroup` に限定 | `scripts/deploy-extra-policy.json`, `template.yaml` |
| 2 | `deploy.yml` の `sam validate/build` ステップで不要な本番ロールの assume が実行されていた | `ci` ジョブから `configure-aws-credentials` を削除。SAM の構文検証・ビルドに AWS 認証は不要であることを明確化 | `.github/workflows/deploy.yml` |

### 重大 (Major)

| # | 指摘内容 | 是正内容 | 対象ファイル |
|---|---------|---------|-------------|
| 1 | README の OIDC 設定値と `deploy.yml` のシークレット名が不一致（`ALARM_EMAIL_STG` 等が未記載） | README の「GitHub Secrets 登録」セクションにすべての使用シークレットを網羅的に記載 | `README.md` |
| 2 | `smoke_test.py` が `ADMIN_USER_PASSWORD_AUTH` を使用。README の「SRP 専用」という記述と矛盾 | README の認証フロー説明を実装に合わせて正確に修正（上の認証フロー設計表を参照）。`smoke_test.py` は staging CI 専用であり `ADMIN_USER_PASSWORD_AUTH` を使う設計は正しいことを明示化 | `README.md`, `scripts/smoke_test.py` |

### 中程度 (Medium)

| # | 指摘内容 | 是正内容 | 対象ファイル |
|---|---------|---------|-------------|
| 1 | API Gateway の `StageName` がハードコードされており、環境変数で動的制御できていなかった | `StageName: !Ref Stage` に修正済み | `template.yaml` |
| 2 | `requirements-runtime.txt` に未使用の `requests` が残存 | `requests` を削除。Lambda の HTTP 通信は `urllib` / `http.client` を使用していることを確認済み | `requirements-runtime.txt` |
| 3 | `test_api.ps1` が認証ヘッダーを含まない不完全なスクリプトだった | `Authorization: $idToken` ヘッダーを含む正しいスクリプトに修正済み | `scripts/test_api.ps1` |

### Flutter フロントエンド追加後の指摘

| # | 指摘内容 | 是正内容 | 対象ファイル |
|---|---------|---------|-------------|
| 1 | バックエンド Pydantic スキーマ（`summary`, `score.value`）と Flutter モデル（`advice`, `score` int）が不一致。API レスポンスが正しく描画されない | `FishingResult` / `FishingScore` / `FishingSeason` を Pydantic スキーマと 1 対 1 で対応するよう全面刷新。`widget_test.dart` にスキーマ整合テストを追加して型の一貫性を自動検証 | `frontend/lib/services/fishing_api_service.dart`, `frontend/test/widget_test.dart` |
| 2 | `home_screen.dart` で `_species`（String）がトップレベル `const _species`（List）を隠す命名バグ。ドロップダウンが正常動作しない | インスタンス変数を `_selectedSpecies` / `_selectedSpot` にリネームして衝突を解消。`r.advice` → `r.summary`、`r.score`（int）→ `r.score.value` に修正 | `frontend/lib/screens/home_screen.dart` |
| 3 | Bedrock 推論結果が空・非正規の場合のエラーハンドリングが未実装 | `score.value == 0 && summary.isEmpty` を異常系として検出し、ユーザーフレンドリーなフォールバック表示を実装 | `frontend/lib/screens/home_screen.dart` |
| 4 | モバイルが `USER_PASSWORD_AUTH` で Cognito と不一致 | **Amplify Auth + SRP** に切替。`AuthException` を日本語メッセージにマッピング | `frontend/lib/services/cognito_service.dart`, `frontend/lib/main.dart`, `frontend/lib/config/amplify_configuration.dart` |
| 5 | `withOpacity`（deprecated）が `home_screen.dart` / `login_screen.dart` に残存 | `withValues(alpha: ...)` に置き換え | `frontend/lib/screens/home_screen.dart` |

---

## AI と協働する開発プロセス（AI-Augmented Development）

本プロジェクトでは、**Cursor** 上の **Claude（Sonnet 系）** を、単なるコード生成ツールではなく、要件整理・設計・レビューまで担う **バーチャルなリードエンジニア／CTO** として位置づけ、人間の開発者と **ペアプログラミング** しながら進めました。**開発の速さと、本番運用に耐える品質**の両立を目指しています。

### AI ネイティブ・デベロップメント

- 仕様の言語化、IaC（AWS SAM）の叩き台、Lambda／テスト／CI の生成を AI と何度もやり取りし、**実装とドキュメントを短いサイクルで揃え**ました。
- 人間がアーキテクチャの意図・運用上の制約・セキュリティ境界を示し、AI がその前提でコードや差分を出す、という **役割分担** をはっきりさせています。

### 厳格なレビューサイクル（多視点の「激辛レビュー」）

- レビュアとして **複数の AI ペルソナ**（例：MLOps／インフラ寄りのリード、プロダクト全体を見る CTO 視点など）を切り替え、同一設計に対して **少なくとも 3 ラウンド**、意図的に厳しい観点から指摘を出しました。
- 各ラウンドの指摘（権限の広さ、ログに残る情報、障害時の挙動、テストの抜けなど）を **修正 → 再レビュー** し、採用した理由は README やコードコメントに **追記できるところまで**整理しました。

### プロフェッショナル品質への到達（シニア水準を基準に）

AI の提案をそのまま採用するのではなく、**あらかじめ品質の基準を決めたうえで**詰めました。README 前半にまとめているとおり、たとえば次の軸で **シニアエンジニアが求める水準**を意識しています。

| 観点 | このリポジトリでの具体例 |
|------|-------------------------|
| **セキュリティ** | デプロイロール IAM の ARN スコープ、推論 Lambda の `PutMetricData` のみ AWS 仕様上の `*`＋条件、GitHub Actions **OIDC**、Cognito SRP（Amplify）／WAF／環境分離 |
| **堅牢性** | Step Functions 上の **Catch とフォールバック**（部分障害でも推論継続）、外部 HTTP の **リトライ戦略**、CloudWatch **アラーム** による劣化検知 |
| **データ品質** | **Pydantic** による API 入出力の検証。非 JSON やスキーマから外れた値を **黙って通さない** 設計 |

（現時点の負荷では上記の境界で先に固めており、キューを挟む処理が増えた段階で **デッドレターキュー（DLQ）の導入**などを検討する余地はあります。）

### 意図的な意思決定（人間が最後に選ぶ）

- AI は選択肢とトレードオフの列挙に強い一方、**本番で許容するリスクやコスト**は人間が決めます。DynamoDB のキー設計、キャッシュの TTL、「外部取得が失敗したときにどこまで推論を続けるか」などは、**その判断の根拠**を対話の中で言語化し、README や `template.yaml` のコメントに残しました。
- **AI の出力を鵜呑みにしない**ことを原則とし、根拠の薄い一般論は採用せず、テスト・IaC・監視で検証できる形に落ちた変更だけをマージ対象としました。

> **まとめ**: 生成 AI はコードを早く書くための道具であると同時に、**設計レビューやドキュメント整備を並行して回す相棒**になり得ます。少人数でも、エンタープライズに近い完成度を目指すときに有効です。次世代のエンジニアには、**プロンプトとコンテキストを設計し、AI の提案を責任をもって採否できる人**が、再現性の高い成果を出せると考えています。
