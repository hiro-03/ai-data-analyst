import 'package:amplify_auth_cognito/amplify_auth_cognito.dart';
import 'package:amplify_flutter/amplify_flutter.dart';
import 'package:flutter/material.dart';

import 'config/amplify_configuration.dart';
import 'screens/login_screen.dart';

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
      home: const LoginScreen(),
    );
  }
}
