import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';

/// Web×stg で InitiateAuth した ID トークンを保持する（Amplify に載らないため）。
///
/// SRP 利用時は Amplify がローカルに保持するため本クラスは no-op。
class AuthSessionStorage {
  AuthSessionStorage._();

  static const _keyIdToken = 'fishing_app_cognito_id_token';

  static bool get _applies => AppConfig.usePasswordAuthOnWeb;

  /// ログイン成功直後に呼ぶ。対象外プラットフォームでは何もしない。
  static Future<void> saveIdTokenIfApplicable(String token) async {
    if (!_applies) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyIdToken, token);
  }

  /// 起動時に有効なトークンがあれば返す。期限切れなら削除する。
  static Future<String?> readValidIdTokenIfApplicable() async {
    if (!_applies) return null;
    final prefs = await SharedPreferences.getInstance();
    final t = prefs.getString(_keyIdToken);
    if (t == null || t.isEmpty) return null;
    if (!_isJwtLikelyValid(t)) {
      await prefs.remove(_keyIdToken);
      return null;
    }
    return t;
  }

  /// ログアウトやアカウント切り替え時に呼ぶ想定（現状未使用）。
  static Future<void> clearIfApplicable() async {
    if (!_applies) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyIdToken);
  }
}

/// JWT の exp をざっくり検証（ネットワーク不要）。
bool _isJwtLikelyValid(String token) {
  try {
    final parts = token.split('.');
    if (parts.length != 3) return false;
    final normalized = base64Url.normalize(parts[1]);
    final payload =
        json.decode(utf8.decode(base64Url.decode(normalized)))
            as Map<String, dynamic>;
    final exp = payload['exp'];
    if (exp is! int) return true;
    final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    return now < exp - 60;
  } catch (_) {
    return false;
  }
}
