import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

/// Cognito USER_PASSWORD_AUTH フローで認証し ID トークンを返す。
class CognitoService {
  static final _endpoint = Uri.parse(
    'https://cognito-idp.${AppConfig.cognitoRegion}.amazonaws.com/',
  );

  /// ログイン。成功時は ID トークン文字列を返す。
  /// 失敗時は [CognitoAuthException] を throw する。
  Future<String> signIn(String username, String password) async {
    final response = await http.post(
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
    );

    final body = jsonDecode(response.body) as Map<String, dynamic>;

    if (response.statusCode != 200) {
      final message = body['message'] as String? ?? '認証エラー';
      throw CognitoAuthException(message);
    }

    final idToken =
        body['AuthenticationResult']?['IdToken'] as String?;
    if (idToken == null) throw CognitoAuthException('トークン取得失敗');
    return idToken;
  }
}

class CognitoAuthException implements Exception {
  CognitoAuthException(this.message);
  final String message;

  @override
  String toString() => message;
}
