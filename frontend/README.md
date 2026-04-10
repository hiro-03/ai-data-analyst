# fishing_app — Flutter フロントエンド

AI 釣りアドバイザーのモバイルクライアント。  
地図上で釣り場を選択し、Cognito 認証後に釣り推論 API を呼び出してアドバイスを表示します。

---

## ディレクトリ構成

```
frontend/
├── lib/
│   ├── main.dart                    # エントリポイント・ルーティング
│   ├── config/
│   │   └── app_config.dart          # Cognito / API URL 設定値
│   ├── screens/
│   │   ├── login_screen.dart        # ログイン画面
│   │   └── home_screen.dart         # 釣り場選択・結果表示画面
│   └── services/
│       ├── cognito_service.dart     # Cognito USER_PASSWORD_AUTH 認証
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

`USER_PASSWORD_AUTH` を使用します。HTTPS（TLS 1.2 以上）上で送信されるため、  
転送中の平文露出はありません。詳細は `lib/services/cognito_service.dart` のコメントを参照してください。

> **注意**: このアプリは AWS バックエンド（API Gateway + Lambda + Cognito）と  
> 組み合わせて使用します。バックエンドのセットアップはルートの `README.md` を参照してください。
