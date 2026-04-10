import 'dart:convert';

import 'app_config.dart';

/// Amplify Auth 用の設定 JSON 文字列を生成する。
///
/// [AppConfig] のユーザープール ID・クライアント ID・リージョンを渡し、
/// Amplify Auth の **既定のサインインフロー（USER_SRP_AUTH / SRP）** で
/// Cognito と通信する。平文パスワードを `InitiateAuth` に載せる
/// `USER_PASSWORD_AUTH` は使用しない。
String buildAmplifyConfiguration() {
  return jsonEncode(<String, dynamic>{
    'UserAgent': 'aws-amplify-cli/2.0',
    'Version': '1.0',
    'auth': <String, dynamic>{
      'plugins': <String, dynamic>{
        'awsCognitoAuthPlugin': <String, dynamic>{
          'UserAgent': 'aws-amplify-cli/0.1.0',
          'Version': '0.1.0',
          'CognitoUserPool': <String, dynamic>{
            'Default': <String, dynamic>{
              'PoolId': AppConfig.cognitoUserPoolId,
              'AppClientId': AppConfig.cognitoClientId,
              'Region': AppConfig.cognitoRegion,
            },
          },
        },
      },
    },
  });
}
