import 'package:amplify_auth_cognito/amplify_auth_cognito.dart';
import 'package:amplify_flutter/amplify_flutter.dart';

// ─────────────────────────────────────────────────────────────────────────────
// 認証方針（SRP / Secure Remote Password）
//
// 本アプリは **AWS Amplify Auth** を用い、Cognito の **USER_SRP_AUTH** により
// サインインする。パスワードの平文はネットワーク上に送信されず、
// `template.yaml` の `ExplicitAuthFlows` も `ALLOW_USER_SRP_AUTH` に整合させている。
//
// CI 向けスクリプト（scripts/smoke_test.py）は OIDC 付きロールから
// **ADMIN_USER_PASSWORD_AUTH** を使う別経路であり、モバイルアプリの実装とは分離している。
// ─────────────────────────────────────────────────────────────────────────────

/// Cognito（SRP）経由でサインインし、API Gateway 用の **ID トークン** を返す。
class CognitoService {
  /// ログイン。成功時は ID トークン文字列を返す。
  /// 失敗時は [CognitoAuthException] を throw する。
  Future<String> signIn(String username, String password) async {
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
