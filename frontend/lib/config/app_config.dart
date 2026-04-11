import 'package:flutter/foundation.dart' show kIsWeb;

/// アプリ設定定数。
/// 本番リリース時は環境変数や --dart-define で差し替えること。
class AppConfig {
  AppConfig._();

  /// Flutter Web かつステージング API 向けビルド（USER_PASSWORD_AUTH 分岐）。
  static bool get usePasswordAuthOnWeb =>
      kIsWeb && fishingApiUrl.contains('/stg/');

  // Amazon Cognito
  static const cognitoRegion = 'ap-northeast-1';
  static const cognitoUserPoolId = 'ap-northeast-1_bW3DE4HiB';
  static const cognitoClientId = '3b0qa4gbdtf75pa4m5pq5sl4uc';

  // API Gateway（ステージング）
  static const fishingApiUrl =
      'https://2ie0f0ucei.execute-api.ap-northeast-1.amazonaws.com/stg/fishing';
}
