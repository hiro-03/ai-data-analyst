import 'dart:async';
import 'dart:convert';

import 'package:amplify_auth_cognito/amplify_auth_cognito.dart';
import 'package:amplify_flutter/amplify_flutter.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

// ─────────────────────────────────────────────────────────────────────────────
// 認証方針
//
// - **モバイル / デスクトップ**: Amplify Auth の既定フロー（USER_SRP_AUTH / SRP）。
// - **Flutter Web × ステージング API**: ブラウザ環境では SRP 実装が失敗することがあるため、
//   Cognito の **USER_PASSWORD_AUTH**（HTTPS 上の InitiateAuth）に切り替える。
//   ステージングのユーザープールクライアントのみ `ALLOW_USER_PASSWORD_AUTH` を有効化している。
// - **本番**（`AppConfig.fishingApiUrl` に `/stg/` が含まれないビルド）: Web でも SRP のみ。
//
// CI の smoke_test.py は **ADMIN_USER_PASSWORD_AUTH**（別経路）。
// ─────────────────────────────────────────────────────────────────────────────

/// Cognito でサインインし、API Gateway 用の **ID トークン** を返す。
class CognitoService {
  /// ログイン。成功時は ID トークン文字列を返す。
  /// 失敗時は [CognitoAuthException] を throw する。
  Future<String> signIn(String username, String password) async {
    if (_usePasswordAuthOnWeb) {
      return _signInWithUserPasswordAuth(username, password);
    }
    return _signInWithAmplifySrp(username, password);
  }

  /// Web かつステージング API 向けビルドでは USER_PASSWORD_AUTH を使う。
  bool get _usePasswordAuthOnWeb => AppConfig.usePasswordAuthOnWeb;

  /// Amplify（USER_SRP_AUTH）。モバイル・デスクトップ、および本番 Web で使用。
  Future<String> _signInWithAmplifySrp(String username, String password) async {
    try {
      final result = await Amplify.Auth.signIn(
        username: username,
        password: password,
      );

      final step = result.nextStep.signInStep;
      if (!result.isSignedIn && step != AuthSignInStep.done) {
        throw CognitoAuthException(
          '追加の認証ステップが必要です（${step.name}）。管理者に問い合わせください。',
        );
      }

      final session = await Amplify.Auth.fetchAuthSession() as CognitoAuthSession;
      final idToken = session.userPoolTokensResult.value.idToken.raw;
      return idToken;
    } on AuthException catch (e) {
      throw CognitoAuthException(_mapAuthException(e));
    } on CognitoAuthException {
      rethrow;
    } catch (e) {
      throw CognitoAuthException('認証に失敗しました: $e');
    }
  }

  /// Cognito HTTP API（USER_PASSWORD_AUTH）。Flutter Web + stg 専用。
  Future<String> _signInWithUserPasswordAuth(
    String username,
    String password,
  ) async {
    final endpoint = Uri.parse(
      'https://cognito-idp.${AppConfig.cognitoRegion}.amazonaws.com/',
    );
    try {
      final response = await http
          .post(
            endpoint,
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
          .timeout(const Duration(seconds: 30));
      final body = jsonDecode(response.body) as Map<String, dynamic>;

      if (response.statusCode != 200) {
        final msg = body['message'] as String? ?? 'Cognito エラー';
        throw CognitoAuthException(_mapCognitoJsonError(msg, body));
      }

      final idToken =
          body['AuthenticationResult']?['IdToken'] as String?;
      if (idToken == null) {
        throw CognitoAuthException('トークンを取得できませんでした');
      }
      return idToken;
    } on TimeoutException {
      throw CognitoAuthException(
        '認証がタイムアウトしました。通信状況を確認してください。',
      );
    } on CognitoAuthException {
      rethrow;
    } catch (e) {
      throw CognitoAuthException('認証に失敗しました: $e');
    }
  }

  String _mapCognitoJsonError(String message, Map<String, dynamic> body) {
    final t = body['__type'] as String? ?? '';
    if (t.contains('NotAuthorized') ||
        message.contains('Incorrect username or password')) {
      return 'メールアドレスまたはパスワードが正しくありません';
    }
    if (t.contains('UserNotConfirmed')) {
      return 'メールアドレスの確認が完了していません';
    }
    if (t.contains('TooManyRequests')) {
      return 'リクエストが多すぎます。しばらくしてから再試行してください';
    }
    // Cognito がクライアントに USER_PASSWORD_AUTH が無いときに返す（stg デプロイ未反映など）
    if (message.contains('USER_PASSWORD_AUTH flow not enabled')) {
      return 'Cognito アプリクライアントでパスワード認証が有効になっていません。インフラを再デプロイするか管理者に連絡してください。';
    }
    return message;
  }

  /// Amplify の例外メッセージをユーザー向け日本語に寄せる。
  String _mapAuthException(AuthException e) {
    final m = e.message;
    if (m.contains('NotAuthorizedException') ||
        m.contains('Incorrect username or password')) {
      return 'メールアドレスまたはパスワードが正しくありません';
    }
    if (m.contains('UserNotConfirmedException')) {
      return 'メールアドレスの確認が完了していません';
    }
    if (m.contains('PasswordResetRequiredException')) {
      return 'パスワードの再設定が必要です';
    }
    if (m.contains('TooManyRequestsException')) {
      return 'リクエストが多すぎます。しばらくしてから再試行してください';
    }
    return m;
  }
}

class CognitoAuthException implements Exception {
  CognitoAuthException(this.message);
  final String message;

  @override
  String toString() => message;
}
