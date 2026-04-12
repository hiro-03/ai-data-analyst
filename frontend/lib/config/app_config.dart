import 'package:flutter/foundation.dart' show kIsWeb;

/// アプリ設定定数。
/// 本番／stg の切り替えは `flutter run` / ビルド時の `--dart-define` で行う。
///
/// 例（本番）:
/// `--dart-define=FISHING_API_URL=https://.../prod/fishing`
/// `--dart-define=COGNITO_USER_POOL_ID=...`
/// `--dart-define=COGNITO_CLIENT_ID=...`
class AppConfig {
  AppConfig._();

  /// Flutter Web かつステージング API 向けビルドのみ true（USER_PASSWORD_AUTH 分岐）。
  /// `kIsWeb` が false のモバイル／デスクトップでは常に false となり、SRP のみが使われる。
  static bool get usePasswordAuthOnWeb =>
      kIsWeb && fishingApiUrl.contains('/stg/');

  // Amazon Cognito（既定はステージング。本番は dart-define で上書き）
  static const cognitoRegion = String.fromEnvironment(
    'COGNITO_REGION',
    defaultValue: 'ap-northeast-1',
  );
  static const cognitoUserPoolId = String.fromEnvironment(
    'COGNITO_USER_POOL_ID',
    defaultValue: 'ap-northeast-1_bW3DE4HiB',
  );
  static const cognitoClientId = String.fromEnvironment(
    'COGNITO_CLIENT_ID',
    defaultValue: '3b0qa4gbdtf75pa4m5pq5sl4uc',
  );

  /// API Gateway `/fishing` の URL（既定は stg）
  static const fishingApiUrl = String.fromEnvironment(
    'FISHING_API_URL',
    defaultValue:
        'https://2ie0f0ucei.execute-api.ap-northeast-1.amazonaws.com/stg/fishing',
  );
}
