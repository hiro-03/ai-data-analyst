import 'package:amplify_auth_cognito/amplify_auth_cognito.dart';
import 'package:amplify_flutter/amplify_flutter.dart';
import 'package:flutter/material.dart';

import 'config/amplify_configuration.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_session_storage.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await _configureAmplify();
  runApp(const FishingApp());
}

/// Amplify Auth（Cognito SRP）を初期化する。二重初期化は避ける。
Future<void> _configureAmplify() async {
  if (Amplify.isConfigured) {
    return;
  }
  await Amplify.addPlugins([AmplifyAuthCognito()]);
  await Amplify.configure(buildAmplifyConfiguration());
}

class FishingApp extends StatelessWidget {
  const FishingApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI 釣りアドバイザー',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.dark(
          primary: const Color(0xFF00BCD4),
          surface: const Color(0xFF0D1F3C),
        ),
        useMaterial3: true,
        fontFamily: 'sans-serif',
      ),
      home: const AuthGate(),
    );
  }
}

/// 起動時に Cognito / ローカル保存トークンを確認し、ホームかログインへ振り分ける。
///
/// 再読み込み後も Amplify SRP のセッションが残っている場合はログイン画面をスキップする。
class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  Widget? _child;

  @override
  void initState() {
    super.initState();
    _resolveInitialRoute();
  }

  Future<void> _resolveInitialRoute() async {
    // Web×stg: HTTP InitiateAuth の ID トークン（Amplify に載らない）
    final webToken = await AuthSessionStorage.readValidIdTokenIfApplicable();
    if (webToken != null) {
      if (!mounted) return;
      setState(() => _child = HomeScreen(idToken: webToken));
      return;
    }

    if (Amplify.isConfigured) {
      try {
        final session = await Amplify.Auth.fetchAuthSession() as CognitoAuthSession;
        if (session.isSignedIn) {
          final idToken = session.userPoolTokensResult.value.idToken.raw;
          if (idToken.isNotEmpty) {
            if (!mounted) return;
            setState(() => _child = HomeScreen(idToken: idToken));
            return;
          }
        }
      } catch (_) {
        // 未ログインまたは取得失敗 → ログイン画面へ
      }
    }

    if (!mounted) return;
    setState(() => _child = const LoginScreen());
  }

  @override
  Widget build(BuildContext context) {
    final child = _child;
    if (child == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return child;
  }
}
