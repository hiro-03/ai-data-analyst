# fishing_app — Flutter フロントエンド

AI 釣りアドバイザーのモバイルクライアント。  
地図上で釣り場を選択し、Cognito 認証後に釣り推論 API を呼び出してアドバイスを表示します。

---

## ディレクトリ構成

```
frontend/
├── lib/
│   ├── main.dart                    # エントリポイント・Amplify 初期化・ルーティング
│   ├── config/
│   │   ├── app_config.dart          # Cognito / API URL 設定値
│   │   └── amplify_configuration.dart # Amplify（SRP）用 JSON 生成
│   ├── screens/
│   │   ├── login_screen.dart        # ログイン画面
│   │   └── home_screen.dart         # 釣り場選択・結果表示画面
│   └── services/
│       ├── cognito_service.dart     # Amplify Auth（Cognito USER_SRP_AUTH / SRP）
│       └── fishing_api_service.dart # 釣り推論 API クライアント
└── test/
    └── widget_test.dart             # ウィジェットテスト + スキーマ整合テスト
```

---

## 前提条件

| ツール | バージョン |
|--------|-----------|
| Flutter SDK | 3.x 以上 |
| Dart SDK | 3.x 以上（Flutter に同梱） |
| Android Studio / Xcode | 各プラットフォームの最新安定版 |

---

## セットアップ

```bash
cd frontend
flutter pub get
```

---

## 設定値の変更

`lib/config/app_config.dart` に Cognito と API Gateway の設定値を記述します。

```dart
static const cognitoRegion     = 'ap-northeast-1';
static const cognitoUserPoolId = 'ap-northeast-1_xxxxxxxx';
static const cognitoClientId   = 'xxxxxxxxxxxxxxxxxxxxxxxx';
static const fishingApiUrl     = 'https://<api-id>.execute-api.ap-northeast-1.amazonaws.com/stg/fishing';
```

実際の値は `sam deploy` 後の CloudFormation Outputs から取得できます。

---

## 実行

```bash
# エミュレータまたは実機で起動
flutter run

# リリースビルド（Android APK）
flutter build apk --release

# リリースビルド（iOS）
flutter build ios --release
```

---

## テスト

```bash
# ウィジェットテスト + スキーマ整合テスト
flutter test
```

`test/widget_test.dart` には、バックエンド（Pydantic `FishingAdviceResponse`）と  
フロントエンド（`FishingResult.fromJson`）の型整合を検証するテストが含まれています。  
バックエンドのスキーマを変更した場合は、このテストも必ず更新してください。

---

## 静的解析

```bash
flutter analyze
```

---

## 認証フロー

**通常（モバイル・Windows デスクトップ）**: **Amplify Auth** の **`USER_SRP_AUTH`（SRP）**。  
**Flutter Web × ステージング**（`fishingApiUrl` に `/stg/` を含むビルド）: ブラウザ上で SRP が不安定な場合があるため、  
Cognito の **`USER_PASSWORD_AUTH`（HTTPS 上の InitiateAuth）** に切り替える。  
`template.yaml` のユーザープールクライアントは **stg のみ** `ALLOW_USER_PASSWORD_AUTH` を有効化している。  
設定・分岐は `lib/services/cognito_service.dart` を参照。

> **注意**: このアプリは AWS バックエンド（API Gateway + Lambda + Cognito）と  
> 組み合わせて使用します。バックエンドのセットアップはルートの `README.md` を参照してください。
>
> **Flutter Web（`flutter run -d chrome`）**: ブラウザはクロスオリジン制限（CORS）のため、  
> API 側で `OPTIONS /fishing` とレスポンスヘッダー `Access-Control-Allow-*` が必要です。  
> 本リポジトリの `template.yaml` に CORS 設定を含めています。  
> **注意**: OpenAPI を変えたあと、API Gateway の **新しい Deployment** がステージに載らないと CORS が効きません。CI では `DeployTimestamp=${{ github.sha }}` を渡して毎回デプロイを更新しています。まだ `Failed to fetch` のときは **最新コミットのデプロイ完了後**に再試行するか、手動で `sam deploy --config-env stg` に `DeployTimestamp` をユニークな値で付与してください。
