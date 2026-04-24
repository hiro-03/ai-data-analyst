# 釣り推論 API

緯度・経度に基づき最寄り観測所を解決し、潮汐・海況・気象の3系統を外部 API から取得したうえで、**Amazon Bedrock エージェント**（`bedrock-agent-runtime` の `InvokeAgent`）により釣りアドバイスを返す **サーバーレス API** です。インフラは **AWS SAM**、デリバリは **GitHub Actions**、実行基盤は AWS のマネージドサービスで構成しています。

---

## 導入

### プロダクトビジョン / 設計思想

- 生成AIは高い表現力を持つ一方、出力の不確実性と外部依存を内包します。本プロジェクトは、その不確実性を**バリデーション、監視、権限制御、デプロイ統制**で扱うことを設計の核としています。  
- 目的は、推論結果を返すこと自体ではなく、**壊さず運用し続けられる AI 機能**としてサービスに載せることです。  
- 推論結果の品質は、モデルの性能だけでなく、入力の整合性、外部データの欠損耐性、認証・権限、変更履歴の追跡可能性によって支えられます。  
- そのため、入出力スキーマ、部分障害時の継続戦略、環境分離、最小権限、CI/CD の承認ゲートを一体で定義しています。  
- 業務系プロダクトに必要な安心感は、単発のデモ品質ではなく、**誰がいつ何を変更し、何が起きたかを追える運用性**から生まれます。  
- 本リポジトリは、生成AIの活用を「実験」ではなく、**継続運用可能なプロダクト機能**として成立させるための実装例です。

---

## コアアーキテクチャと ML 信頼性

認証、外部データ取得、推論、監視を明確に分離することで、不正アクセスの防止、外部依存による停止回避、品質劣化の早期検知を実現しています。

### システム構成

```text
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
       │               各取得失敗時は Catch により推論を継続（部分障害許容）
       │
       └─ FishingInferenceLambda
            ├─ Amazon Bedrock エージェント（InvokeAgent）呼び出し
            ├─ Pydantic による出力スキーマ検証（非 JSON・範囲外の値は例外）
            └─ CloudWatch カスタムメトリクス（AdviceScore）送信
```

| レイヤー | サービス | 役割 |
|---------|---------|------|
| セキュリティ | Cognito / WAFv2 | JWT 認証・レート制限・マネージドルール |
| 計算 | Lambda（Python 3.11）/ Step Functions Express | 推論オーケストレーション |
| ストレージ | DynamoDB（2テーブル） | 観測所マスタ・外部 API キャッシュ（TTL + PITR） |
| 可観測性 | CloudWatch Alarms / X-Ray / SNS | 品質劣化の検知・分散トレース・アラート |
| CI/CD | GitHub Actions / AWS SAM | OIDC・stg E2E ゲート・prod 手動承認 |

### 推論レイヤーと用語

- 推論は **Amazon Bedrock のエージェント**を **`bedrock-agent-runtime` の `InvokeAgent`** で呼び出します。エージェント ID・エイリアス ID は SSM（`/ai-data-analyst/bedrock/agent/*`）経由で Lambda に渡します。  
- **Amazon Bedrock AgentCore**（URL に `bedrock-agentcore` を含むレジストリ／ランタイム等）は、本リポジトリのコードパスとは**別製品**です。エージェントの構築は **Amazon Bedrock 本体**（モデルアクセス・エージェント作成）から行います。

### ML 信頼性設計

AI の不確実性を業務上許容できる形に変換するため、以下を設計に組み込んでいます。

- **スキーマ検証**  
  Pydantic によりリクエストと推論応答の両方を検証します。非 JSON や範囲外の値を成功レスポンスに混在させず、**品質のサイレント劣化**を防ぎます。

- **部分障害許容**  
  潮汐・海況・気象の取得は並列化し、失敗分岐は Step Functions 上で Catch します。外部依存の一部失敗で API 全体を停止させず、**完全停止の回避**を優先します。

- **監査可能性**  
  エージェント ID・エイリアス・ARN スコープを SSM と IaC に外出しし、Lambda に直書きしません。これにより、**誰が、いつ、どのエージェントを本番に載せ替えたか**を追跡しやすくしています。

- **指標設計**  
  オフライン正解率より先に、AdviceScore カスタムメトリクス、スコア閾値、一定期間の劣化アラームを用い、**本番での動作信頼性**を優先的に監視します。

---

## セキュリティとデリバリー

AI 機能の信頼性は、推論ロジック単体では成立しません。不正アクセスの防止、安全な変更反映、環境ごとの差異統制を一体で扱う必要があります。

### セキュリティ・バイ・デザイン

- **最小権限**  
  GitHub Actions 用デプロイロール（`scripts/deploy-extra-policy.json`）は `Resource: "*"` を用いません。各リソースはアカウント・プレフィックス、または stg/prod の API Gateway RestApi ID で固定した ARN に限定します。Bedrock の `GetAgent` 等はデプロイロール経由で呼ばない前提とし、推論 Lambda の `cloudwatch:PutMetricData` のみ、AWS 仕様上 `Resource: "*"` と `cloudwatch:namespace` 条件を組み合わせています。  
- **ARN プレフィックス制御**  
  アラーム名・SNS・ロググループ・SSM パスなど、命名規則 `ai-data-analyst-fishing*` に揃えた末尾ワイルドカードのみを許容し、広範囲 `Resource:*` とは区別しています。  
- **ポリシーの正本管理**  
  `infra/*.json` には過去のドラフトが残り得ます。運用で attach するインラインポリシーは **`scripts/deploy-extra-policy.json`** を正とします。  
- **Bedrock ARN のスコープ**  
  `template.yaml` の `BedrockAgentArn` 既定値は単独の `"*"` を用いず、`arn:aws:bedrock:ap-northeast-1:476963918877:agent/*` など、当アカウント内エージェントに限定します。  
- **OIDC**  
  長期 IAM アクセスキーを置かず、GitHub Actions は一時クレデンシャルで AWS を操作します。ロールは stg（`AWS_ROLE_ARN_STG`）と prod（`AWS_ROLE_ARN_PROD`）で分離しています。  
- **環境分離**  
  `Stage`（`stg` / `prod`）により、DynamoDB 削除保護、Cognito 認証フロー、Step Functions 実行データのログ記録有無、API Gateway ステージ名、CloudWatch アラームのディメンション等を切り替えます。  
- **入力・出力の固定**  
  Pydantic により API の入口と Bedrock 応答の両方を検証し、`ValidationError` 時は Step Functions を `FAILED` として処理します。  
- **Cognito**  
  `AllowAdminCreateUserOnly: true` と `PreventUserExistenceErrors: ENABLED` により、自己登録の抑止とユーザー列挙耐性を確保します。`ALLOW_USER_PASSWORD_AUTH` / `ALLOW_ADMIN_USER_PASSWORD_AUTH` は **staging のみ**（`IsNotProd`）有効です。モバイル・デスクトップは SRP、Flutter Web（stg）は HTTPS 上の `USER_PASSWORD_AUTH` を許可する構成です。

### デリバリーパイプライン

変更を安全に本番へ届けるため、ローカル検証、stg デプロイ、E2E ゲート、prod 承認を分離しています。

```text
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
    │   失敗時は本番ジョブを実行しない
    ▼
[Job 4] prod デプロイ（production ロール・手動承認必須）
    └─ GitHub Environments の Required reviewers
```

---

## 付録 / 詳細資料

### 付録A — デプロイ・秘密情報・運用手順

#### A.1 GitHub Actions OIDC（初回）

長期 IAM キーは用いず、OIDC フェデレーションで一時クレデンシャルを使用します。

```bash
# 1. OIDC プロバイダー（1アカウントに1回）
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. IAM ロール: trust = scripts/github-actions-trust-policy.json
#    inline = scripts/deploy-extra-policy.json

# 3. GitHub Secrets: 下表と .github/workflows/deploy.yml の参照名を一致させる
#    本パイプラインは AWS Secrets Manager を直接参照しない

# 4. Environments: staging / production
```

#### GitHub Secrets（`deploy.yml` との対応）

変数名はリポジトリ Secrets または Environment Secrets（同名なら Environment 優先）です。

| Secret 名 | 必須 | 用途 | `deploy.yml` 内の参照 |
|-----------|:----:|------|------------------------|
| `AWS_ROLE_ARN_STG` | ✅ | ステージング用 IAM ロール ARN | `secrets.AWS_ROLE_ARN_STG` |
| `AWS_ROLE_ARN_PROD` | ✅ | 本番デプロイ用 IAM ロール ARN | `secrets.AWS_ROLE_ARN_PROD` |
| `ALARM_EMAIL_STG` | 任意 | stg アラートメール | `secrets.ALARM_EMAIL_STG` |
| `BEDROCK_AGENT_ARN_STG` | 任意 | stg 用 Bedrock エージェント ARN | `secrets.BEDROCK_AGENT_ARN_STG` |
| `STG_SMOKE_USER_EMAIL` | E2E 利用時 | stg スモーク用 Cognito ユーザー | `secrets.STG_SMOKE_USER_EMAIL` |
| `STG_SMOKE_USER_PASSWORD` | E2E 利用時 | 上記パスワード | `secrets.STG_SMOKE_USER_PASSWORD` |
| `ALARM_EMAIL` | 任意 | 本番アラートメール | `secrets.ALARM_EMAIL` |
| `BEDROCK_AGENT_ARN` | 任意 | 本番 Bedrock エージェント ARN | `secrets.BEDROCK_AGENT_ARN` |

#### A.2 手動デプロイ（`sam`）

`--parameter-overrides` のキーは **CloudFormation パラメータ名**です。

| パラメータ名（`template.yaml`） | 主な用途 |
|--------------------------------|----------|
| `DeployTimestamp` | API 再デプロイ用（CI は `github.sha` を想定） |
| `Stage` | `stg` または `prod` |
| `WafRateLimitPer5Min` | WAF レート制限（5 分） |
| `ApiAccessLogRetentionDays` | API アクセスログ保持 |
| `AlarmEmail` | CloudWatch アラート通知先（`ALARM_*` と対応） |
| `BedrockAgentArn` | InvokeAgent の IAM スコープ（`BEDROCK_AGENT_*` と対応） |

```powershell
sam validate --template-file template.yaml --lint
sam build

sam deploy --config-env stg `
  --parameter-overrides AlarmEmail="stg-alert@example.com" Stage="stg"

sam deploy --config-env default `
  --parameter-overrides `
    AlarmEmail="prod-alert@example.com" `
    BedrockAgentArn="arn:aws:bedrock:ap-northeast-1:123456789012:agent/AGENTID" `
    Stage="prod"
```

#### A.3 外部 API キー（SSM Parameter Store）

```bash
aws ssm put-parameter \
  --name "/ai-data-analyst/external/stormglass/api-key" \
  --type "SecureString" \
  --value "<YOUR_API_KEY>" \
  --overwrite
```

#### A.4 観測所マスタの投入

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\seed_stations.ps1 `
  -StackName ai-data-analyst-fishing `
  -Region ap-northeast-1
```

#### A.5 Cognito とクライアントの認証フロー

デプロイ後、CloudFormation Outputs に `CognitoUserPoolId` と `CognitoUserPoolClientId` が出力されます。

| フロー | 利用主体 | 本番 | staging | 備考 |
|--------|---------|:----:|:-------:|------|
| `USER_SRP_AUTH` | Flutter モバイル・Windows（Amplify Auth） | ✅ | ✅ | 平文パスワードをネットワークに載せない。 |
| `USER_PASSWORD_AUTH` | Flutter Web × stg | ❌ | ✅ | ブラウザ上の SRP 制約に対するフォールバック。HTTPS。 |
| `ADMIN_USER_PASSWORD_AUTH` | `scripts/smoke_test.py`（CI） | ❌ | ✅ | 呼び出し元に AWS IAM が必要。 |

本番のユーザープールクライアントには `USER_PASSWORD_AUTH` を含めません。CLI 検証は `admin-initiate-auth` または CI の ADMIN フローを用います。

##### テストユーザー作成

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

##### ID トークン（管理者 CLI）

`ADMIN_USER_PASSWORD_AUTH` は IAM 認証を要するため、パスワード単体の公開フローではありません。

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id <USER_POOL_ID> \
  --client-id <APP_CLIENT_ID> \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME="demo@example.com",PASSWORD="<STRONG_PASSWORD>"
```

レスポンスの `AuthenticationResult.IdToken` を API 呼び出しに使用します。

#### A.6 API 呼び出し例

```powershell
$token = "<ID_TOKEN>"
curl.exe -s -X POST `
  "https://<restApiId>.execute-api.ap-northeast-1.amazonaws.com/<stage>/fishing" `
  -H "Content-Type: application/json" `
  -H "Authorization: $token" `
  -d '{"lat":35.681236,"lon":139.767125,"target_species":"aji","spot_type":"harbor"}'
```

`scripts/test_api.ps1` は CloudFormation Outputs の取得と Cognito 認証まで一括で実行します。

```powershell
.\scripts\test_api.ps1 -StackName ai-data-analyst-fishing
```

#### A.7 外部データの取得とキャッシュ

##### 気象（気象庁 JMA）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `https://www.jma.go.jp/bosai/forecast/data/forecast/{officeCode}.json` |
| キャッシュキー | `forecast:jma:<office_code>:<YYYY-MM-DD>` |
| TTL | +2日 |
| 備考 | 緯度・経度から最寄りの気象台コードを解決（47地点マッピング） |

##### 潮汐（Stormglass）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `GET /v2/tide/extremes` |
| キャッシュキー | `tide:stormglass:<lat>:<lon>:<YYYY-MM-DD>` |
| TTL | +2日 |

##### 海況（Open-Meteo Marine）

| 項目 | 内容 |
|-----|-----|
| エンドポイント | `https://marine-api.open-meteo.com/v1/marine` |
| 取得変数 | 海面水温・波高・波向・周期 |
| キャッシュキー | `marine:openmeteo:<lat>:<lon>:<YYYY-MM-DDTHH>` |
| TTL | +3時間 |

並列取得のいずれかが失敗しても、Catch により推論は継続し、利用可能な系列のみを渡します。欠損は結果の `evidence` 側に反映されます。

#### A.8 監視とログ

初回デプロイ後、SNS メール登録の確認が必要です。

| アラーム | 条件 | 目的 |
|-----------|------|------|
| `FishingApi5xxAlarm` | 1分評価を5回、そのうち3回以上で 5xx ≥ 1 | API Gateway 層の障害 |
| `FishingApiProxyErrorsAlarm` | 同上で Lambda エラー ≥ 1 | API プロキシ Lambda の異常 |
| `InferenceScoreAbsoluteAlarm` | 1時間平均スコア < 50 が2時間継続 | 急激な品質低下 |
| `InferenceScoreDriftRatioAlarm` | 1時間平均 < 45 が24時間で16回以上 | 緩慢な品質劣化 |

| ログ種別 | パス例 |
|---------|--------|
| API Gateway | `/aws/apigateway/<stack>/<stage>/access` |
| Step Functions | `/aws/stepfunctions/<stack>/FishingAdviceStateMachine` |
| Lambda | `/aws/lambda/<function-name>` |

**本番**（`Stage=prod`）では、Step Functions の実行データ（入出力）を CloudWatch Logs に残しません。外部 API のレスポンス内容や位置情報をログに流さないためです。**staging** では障害調査用に残します。

##### HTTP 502 / 504

API プロキシ Lambda は Step Functions の同期実行（`StartSyncExecution`）が `SUCCEEDED` 以外のとき **502**、タイムアウト時は **504** を返します。レスポンス JSON には `error` に状態名、`cause` に失敗理由が含まれます。

| 仮説 | 確認先 |
|------|--------|
| 最寄り気象台解決に失敗 | `*-resolve_nearest_station` のログ、`STATIONS_TABLE` |
| `InvokeAgent` 失敗・SSM の ID 不一致 | `*-fishing_infer` のログ、`/ai-data-analyst/bedrock/agent/*` |
| エージェントが JSON 以外を返す・スキーマ不一致 | 同上ログ（`ValueError` / `ValidationError`） |
| 実行時間超過 | 外部 API 遅延・推論レイテンシ |

**`cause` に `accessDeniedException` / `Access denied when calling Bedrock` が含まれる場合**

`InvokeAgent` が IAM またはアカウント設定で拒否されています。以下を順に確認します。

| 確認 | 内容 |
|------|------|
| 推論 Lambda の IAM | `bedrock:InvokeAgent` が `agent`・`agent-alias` の ARN（SSM の ID と一致）に付与されているか。テンプレート更新後は再デプロイが必要。`bedrock-agent-runtime:InvokeAgent` 等の誤アクション名は除く。 |
| ロールの境界・SCP | Permissions boundary や Organization の SCP で `bedrock:*` が拒否されていないか。 |
| 基盤モデル | モデルカタログ／Playgroundで利用可否、Anthropic 初回ユースケース提出の有無を確認。 |
| エージェントの Execution role | Lambda の IAM が正しくても、エージェント内部のサービスロールに `bedrock:InvokeModel` 等が無いと同様の AccessDenied が返る。 |
| コンソールとの比較 | 同一エイリアスで Bedrock の Test が通るか。片方のみ成功する場合は呼び出し元ロール、両方失敗する場合はエージェント／モデル側を先に確認。 |
| エージェントの再準備 | 設定変更後、エージェントを `Save -> Prepare` し、エイリアスを最新の準備済みバージョンに更新する。 |

推論 Lambda のログに出力される **`InvokeAgent 予定: agent_id=... agent_alias_id=... AWS_REGION=...`** を、SSM と Bedrock コンソールの ID と照合します。

### 付録B — ローカル開発

```bash
# Bedrock なしでレスポンス形式のみ確認
INFERENCE_PROVIDER=mock python lambdas/fishing/infer/lambda_function.py

# 単体テスト
pytest tests/ --cov=lambdas --cov=layers --cov-report=term-missing

# 型検査
mypy layers/fishing_common/fishing_common/ lambdas/ \
  --ignore-missing-imports --explicit-package-bases
```

`pip install -r requirements-dev.txt` の後に `pre-commit install` を実行すると、コミット時に `scripts/virtual_cto_gate.py --fast`（pytest + mypy）が実行されます。

```bash
pre-commit install
pre-commit run --all-files
```

`main` への push 時、CI Job Summary にレビュー用チェックリストが Markdown で付与されます。PR 作成時は `.github/pull_request_template.md` を利用します。

### 付録C — 外部レビューに基づく是正記録

#### 最終ゲート（3点）

1. **IAM**  
   `scripts/deploy-extra-policy.json` は `Resource: "*"` を用いません。WAF と API Gateway ステージの関連付けは `restapis/2ie0f0ucei/stages/*`（stg）と `restapis/kgiv7wxd8l/stages/*`（prod）に限定しています。`BedrockAgentArn` の単独 `*` は廃止し、Step Functions ログ配信は `SfnLogGroup` に限定しています。`cloudwatch:PutMetricData` は AWS 仕様上 `Resource: "*"` と `cloudwatch:namespace` 条件を組み合わせています。  
2. **Secrets とドキュメント**  
   GitHub Secrets 名と `.github/workflows/deploy.yml` の `secrets.*` を一致させ、`BEDROCK_AGENT_*` 未設定時の `BedrockAgentArn` は `template.yaml` の既定値と揃えています。  
3. **Cognito とクライアント**  
   IaC では `ALLOW_USER_SRP_AUTH` を常時有効化し、`ALLOW_USER_PASSWORD_AUTH` / `ALLOW_ADMIN_USER_PASSWORD_AUTH` は stg のみ有効です。Flutter は Web×stg URL のみ `USER_PASSWORD_AUTH`、その他は Amplify SRP、CI は `ADMIN_USER_PASSWORD_AUTH` を用います。

#### 指摘分類表

##### Fatal

| 内容 | 是正 |
|------|------|
| `deploy-extra-policy.json` の広い Resource | スコープ限定。WAF 関連の RestApi ID 固定。不要 Bedrock 読み取り Statement 削除。Step Functions ログは `SfnLogGroup` に限定。 |
| `ci` ジョブの不要 assume | `sam validate` / `sam build` から `configure-aws-credentials` を除去。 |

##### Major

| 内容 | 是正 |
|------|------|
| README と `deploy.yml` の Secret 名不一致 | Secrets 表を実装と同期。 |
| `smoke_test.py` と README の SRP 記述の矛盾 | 実装に合わせて認証フローを修正。 |

##### Medium

| 内容 | 是正 |
|------|------|
| API Gateway の `StageName` 固定 | `!Ref Stage` に修正。 |
| 未使用 `requests` | 削除。HTTP は `urllib` / `http.client` を使用。 |
| `test_api.ps1` の認証欠落 | `Authorization: IdToken` を付与。 |

##### Flutter 追補

| 内容 | 是正 |
|------|------|
| Pydantic と Flutter モデル不一致 | スキーマ 1:1 対応、`widget_test` 追加。 |
| 変数名衝突（`_species` 等） | リネーム、API フィールド名整合。 |
| 空レスポンスの扱い | 異常系表示を追加。 |
| モバイルの `USER_PASSWORD_AUTH` | Amplify SRP へ切り替え。 |
| `withOpacity` 非推奨 | `withValues(alpha: ...)` に置換。 |

### 付録D — LLM 支援下での開発補足

仕様の言語化、IaC の下書き、テスト補助に **Cursor / LLM** を用いています。最終判断は人間が行い、変更は **テスト・IaC・監視**で検証可能なものに限定しています。

| 観点 | 例 |
|------|-----|
| セキュリティ | デプロイロールの ARN スコープ、OIDC、Cognito・WAF、環境分離 |
| 堅牢性 | Step Functions の Catch、HTTP リトライ、CloudWatch アラーム |
| データ品質 | Pydantic による入出力の固定 |

将来的にキュー越しの処理が増えた段階では、DLQ 等の導入を検討します。
