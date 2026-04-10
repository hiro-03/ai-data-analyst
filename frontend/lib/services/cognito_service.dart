import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

// ─────────────────────────────────────────────────────────────────────────────
// 認証フロー設計の根拠（全層整合の記録）
//
// モバイルクライアント（Flutter）では USER_PASSWORD_AUTH フローを採用している。
//
// 【SRP ではなく USER_PASSWORD_AUTH を選択した理由】
//   1. Amplify SDK なしで SRP（Secure Remote Password）を実装するには
//      256-bit BigInteger 演算のカスタム実装が必要となり、依存ライブラリが増大する。
//   2. USER_PASSWORD_AUTH は HTTPS（TLS 1.2 以上）上で送信されるため、
//      転送中の平文露出はない（End-to-End Encryption と同等の保護）。
//   3. この設計判断は template.yaml の ExplicitAuthFlows に
//      `ALLOW_USER_PASSWORD_AUTH` を明示的に記載することで意図を表明している。
//
// 【ADMIN_USER_PASSWORD_AUTH との違い】
//   - ADMIN_USER_PASSWORD_AUTH はサーバ側で AWS IAM 認証が必要。
//     staging の CI スモークテスト（scripts/smoke_test.py）でのみ使用。
//     本番の Cognito アプリクライアントでは IsNotProd 条件により無効。
//   - このクラスが使用する USER_PASSWORD_AUTH はクライアントから直接
//     Cognito エンドポイントを呼ぶフローであり、IAM 認証は不要。
//
// 【将来の移行パス】
//   Amplify SDK（amplify_auth_cognito）を導入すれば、このクラスを
//   Amplify の signIn に置き換えることで SRP に切り替え可能。
// ─────────────────────────────────────────────────────────────────────────────

/// Cognito USER_PASSWORD_AUTH フローで認証し ID トークンを返す。
class CognitoService {
  static final _endpoint = Uri.parse(
    'https://cognito-idp.${AppConfig.cognitoRegion}.amazonaws.com/',
  );

  /// ログイン。成功時は ID トークン文字列を返す。
  /// 失敗時は [CognitoAuthException] を throw する。
  Future<String> signIn(String username, String password) async {
    final http.Response response;
    try {
      response = await http
          .post(
            _endpoint,
            headers: {
              'Content-Type': 'application/x-amz-json-1.1',
              'X-Amz-Target':
                  'AWSCognitoIdentityProviderService.InitiateAuth',
            },
            body: jsonEncode({
              'AuthFlow': 'USER_PASSWORD_AUTH',
              'ClientId': AppConfig.cognitoClientId,
              'AuthParameters': {
                'USERNAME': username,
                'PASSWORD': password,
              },
            }),
          )
          // 釣り場（屋外・モバイル回線）での遅延を考慮して 15 秒に設定。
          .timeout(const Duration(seconds: 15));
    } on TimeoutException {
      throw CognitoAuthException(
          '認証がタイムアウトしました。通信状況を確認してください。');
    } catch (e) {
      if (e is CognitoAuthException) rethrow;
      throw CognitoAuthException('ネットワークエラーが発生しました');
    }

    Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw CognitoAuthException('レスポンスの解析に失敗しました');
    }

    if (response.statusCode != 200) {
      // Cognito のエラーコードに基づいてユーザーフレンドリーなメッセージに変換。
      final errorCode = body['__type'] as String? ?? '';
      throw CognitoAuthException(_mapCognitoError(errorCode, body));
    }

    final idToken =
        body['AuthenticationResult']?['IdToken'] as String?;
    if (idToken == null) {
      throw CognitoAuthException('トークン取得失敗: IdToken が含まれていません');
    }
    return idToken;
  }

  /// Cognito エラーコードを日本語メッセージに変換する。
  String _mapCognitoError(String code, Map<String, dynamic> body) {
    switch (code) {
      case 'NotAuthorizedException':
        return 'メールアドレスまたはパスワードが正しくありません';
      case 'UserNotFoundException':
        // PreventUserExistenceErrors=ENABLED の場合も同一メッセージにする。
        return 'メールアドレスまたはパスワードが正しくありません';
      case 'UserNotConfirmedException':
        return 'メールアドレスの確認が完了していません';
      case 'PasswordResetRequiredException':
        return 'パスワードの再設定が必要です。管理者にお問い合わせください';
      case 'TooManyRequestsException':
        return 'リクエストが多すぎます。しばらく時間をおいてから再試行してください';
      default:
        return body['message'] as String? ?? '認証エラーが発生しました';
    }
  }
}

class CognitoAuthException implements Exception {
  CognitoAuthException(this.message);
  final String message;

  @override
  String toString() => message;
}
