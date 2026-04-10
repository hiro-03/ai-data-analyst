# 釣り推論 API（本番運用品質）

クライアントから送られた **緯度・経度** に基づき **最寄りの観測所を特定**し、
潮汐・海況・気象の **3 系統**のデータを外部 API から取得したうえで、
**Amazon Bedrock AgentCore** により釣りのアドバイスを返すサーバーレス API です。

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
            ├─ Bedrock AgentCore（InvokeAgent）呼び出し
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

---

## セキュリティ設計方針

- **最小権限の原則**: GitHub Actions 用デプロイロールの IAM ポリシーでは、各リソースをプロジェクト名プレフィックス（`ai-data-analyst-fishing*`）で **範囲を限定**しています。`Resource: "*"` が残る箇所（X-Ray・ログ配信 API など）は AWS 側の仕様上やむをえないため、`scripts/deploy-extra-policy.json` のコメントで理由を記載しています。
- **OIDC 認証**: 長期の IAM アクセスキーを置かず、GitHub Actions から一時クレデンシャルで AWS を操作します。ロールは stg（`AWS_ROLE_ARN_STG`）と prod（`AWS_ROLE_ARN_PROD`）で分けています。
- **環境分離**: `Stage` パラメータ（`stg` / `prod`）により、DynamoDB の削除保護、Cognito の認証フロー、Step Functions の実行データのログ記録の有無、API Gateway のステージ名、CloudWatch アラームのディメンションなどを **環境ごとに切り替え**ます。
- **Pydantic バリデーション**: API の入口（リクエスト）と推論の出口（Bedrock レスポンス）の **両方**でスキーマ検証します。Bedrock が非 JSON や範囲外の値を返した場合は `ValidationError` とし、Step Functions の実行は `FAILED` になります。推論結果の **見かけ上の成功による品質劣化**を防ぎます。
- **Cognito 強化設定**:
  - `AllowAdminCreateUserOnly: true`（自己登録禁止）
  - `PreventUserExistenceErrors: ENABLED`（ユーザー列挙攻撃の抑止）
  - `ALLOW_ADMIN_USER_PASSWORD_AUTH` は staging 環境のみ有効（`IsNotProd` 条件）。本番は SRP 専用。

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

> **認証フロー設計（全環境共通）**
>
> | フロー | 利用主体 | 本番 | staging | 備考 |
> |--------|---------|:----:|:-------:|------|
> | `USER_PASSWORD_AUTH` | Flutter モバイルクライアント | ✅ | ✅ | HTTPS 上で送信。Amplify SDK なしで SRP を実装するコストを避けた設計判断。転送中の平文露出は TLS で保護される。 |
> | `USER_SRP_AUTH` | 将来の Amplify 対応クライアント | ✅ | ✅ | SRP はクライアント側でパスワードハッシュを計算する。現状は Flutter から直接呼ばない。 |
> | `ADMIN_USER_PASSWORD_AUTH` | CI スモークテスト（`smoke_test.py`） | ❌ | ✅ | AWS IAM 認証が必要。`IsNotProd` 条件で本番では無効。 |
>
> > **設計の根拠**: `USER_PASSWORD_AUTH` は `ADMIN_USER_PASSWORD_AUTH` とは異なりクライアントが直接 Cognito エンドポイントを呼べるため、モバイル用途に適切。`template.yaml` の `ExplicitAuthFlows` に明示的に記載することで意図を全層で共有している（`cognito_service.dart` のコメントも参照）。

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
mypy layers/fishing_common/python/fishing_common/ lambdas/ \
  --ignore-missing-imports --explicit-package-bases
```

---

## CTO レビュー指摘事項と是正記録

本プロジェクトは外部 CTO 視点による厳格なコードレビューを受け、以下の指摘を是正した記録を誠実に開示します。

### 致命的 (Fatal)

| # | 指摘内容 | 是正内容 | 対象ファイル |
|---|---------|---------|-------------|
| 1 | `deploy-extra-policy.json` に `Resource: "*"` のワイルドカードが残存 | X-Ray・Logs Delivery は AWS サービス仕様上リソース ARN を指定できないため、`Resource: "*"` の必要性を Sid コメントで明示。他のすべての Statement は ARN スコープ済み | `scripts/deploy-extra-policy.json` |
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
| 4 | `cognito_service.dart` にタイムアウト・エラーマッピングがなく、釣り場（モバイル回線）での利用に不適 | 15 秒タイムアウト・Cognito エラーコード別日本語メッセージ変換を実装 | `frontend/lib/services/cognito_service.dart` |
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
| **セキュリティ** | IAM の最小権限・スコープ、`Resource: "*"` が残る箇所の文書化、GitHub Actions の **OIDC** による長期キー排除、Cognito／WAF／環境分離 |
| **堅牢性** | Step Functions 上の **Catch とフォールバック**（部分障害でも推論継続）、外部 HTTP の **リトライ戦略**、CloudWatch **アラーム** による劣化検知 |
| **データ品質** | **Pydantic** による API 入出力の検証。非 JSON やスキーマから外れた値を **黙って通さない** 設計 |

（現時点の負荷では上記の境界で先に固めており、キューを挟む処理が増えた段階で **デッドレターキュー（DLQ）の導入**などを検討する余地はあります。）

### 意図的な意思決定（人間が最後に選ぶ）

- AI は選択肢とトレードオフの列挙に強い一方、**本番で許容するリスクやコスト**は人間が決めます。DynamoDB のキー設計、キャッシュの TTL、「外部取得が失敗したときにどこまで推論を続けるか」などは、**その判断の根拠**を対話の中で言語化し、README や `template.yaml` のコメントに残しました。
- **AI の出力を鵜呑みにしない**ことを原則とし、根拠の薄い一般論は採用せず、テスト・IaC・監視で検証できる形に落ちた変更だけをマージ対象としました。

> **まとめ**: 生成 AI はコードを早く書くための道具であると同時に、**設計レビューやドキュメント整備を並行して回す相棒**になり得ます。少人数でも、エンタープライズに近い完成度を目指すときに有効です。次世代のエンジニアには、**プロンプトとコンテキストを設計し、AI の提案を責任をもって採否できる人**が、再現性の高い成果を出せると考えています。
