// ─────────────────────────────────────────────────────────────────────────────
// バックエンドとフロントエンドの「型の一貫性」を保証するテスト。
//
// FishingResult スキーマ整合テストは、バックエンド（Pydantic FishingAdviceResponse）
// が返す JSON と Flutter（FishingResult.fromJson）のマッピングが
// 正しく対応していることを自動検証します。
//
// バックエンドのスキーマ定義（参照元）:
//   layers/fishing_common/python/fishing_common/schemas.py
// ─────────────────────────────────────────────────────────────────────────────

import 'package:flutter_test/flutter_test.dart';
import 'package:fishing_app/main.dart';
import 'package:fishing_app/services/fishing_api_service.dart';

void main() {
  group('アプリ基本表示テスト', () {
    testWidgets('ログイン画面のタイトルが表示される', (WidgetTester tester) async {
      await tester.pumpWidget(const FishingApp());
      // AuthGate が非同期で初期ルートを解決するまで待つ
      await tester.pumpAndSettle();
      expect(find.text('AI 釣りアドバイザー'), findsOneWidget);
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // FishingResult スキーマ整合テスト
  //
  // 以下のテストが通ることで、バックエンドのスキーマ変更が
  // フロントエンドの描画を壊さないことを保証します。
  // ─────────────────────────────────────────────────────────────────────────
  group('FishingResult スキーマ整合テスト', () {
    // バックエンドが返す典型的な JSON（Pydantic FishingAdviceResponse.model_dump()）。
    // バックエンドの schemas.py を変更した場合、このテストも更新してください。
    const backendResponseJson = <String, dynamic>{
      'summary': '波は穏やか。アジングに最適な条件です。',
      'score': <String, dynamic>{'value': 82.0, 'label': 'excellent'},
      'season': <String, dynamic>{'month': 4, 'label': 'spring'},
      'best_windows': <String>['06:00–08:00', '18:00–20:00'],
      'recommended_tactics': <String>['アジング', 'サビキ'],
      'risk_and_safety': <String>[],
      'evidence': <String>['風速 < 5m/s', '波高 < 0.5m'],
      'trace_id': 'abc12345-0000-0000-0000-000000000000',
      'latency_ms': 1234,
    };

    test('バックエンドスキーマを正しくパースできる', () {
      final result = FishingResult.fromJson(backendResponseJson);

      // summary（旧 advice ではないことを明示的に検証）
      expect(result.summary, '波は穏やか。アジングに最適な条件です。');

      // score は FishingScore オブジェクト（value: float, label: string）
      expect(result.score.value, 82.0);
      expect(result.score.label, 'excellent');
      // stars: 82 / 20 = 4.1 → 切り捨て 4
      expect(result.score.stars, 4);

      // season
      expect(result.season.month, 4);
      expect(result.season.label, 'spring');

      // リスト項目
      expect(result.bestWindows, ['06:00–08:00', '18:00–20:00']);
      expect(result.recommendedTactics, ['アジング', 'サビキ']);
      expect(result.riskAndSafety, isEmpty);
      expect(result.evidence, ['風速 < 5m/s', '波高 < 0.5m']);

      // API プロキシが付与するメタ情報
      expect(result.traceId, 'abc12345-0000-0000-0000-000000000000');
      expect(result.latencyMs, 1234);
    });

    test('score フィールドが Map でない場合にフォールバックする', () {
      // Bedrock 推論が異常終了して score が非 Map で返った場合の防御テスト。
      final result = FishingResult.fromJson(<String, dynamic>{
        'summary': 'テスト',
        'score': 'invalid_string', // 正常時は Map だが異常値を想定
        'season': null,
        'trace_id': '',
        'latency_ms': 0,
      });

      expect(result.score.value, 0.0);
      expect(result.score.label, '');
      expect(result.season.month, 0);
    });

    test('staging の mock プロバイダーレスポンスもパースできる', () {
      // staging 環境（INFERENCE_PROVIDER=mock）のレスポンス形式を検証する。
      const mockResponse = <String, dynamic>{
        'summary': 'モック推論結果（本番は INFERENCE_PROVIDER=bedrock-agentcore を設定）',
        'score': <String, dynamic>{'value': 50.0, 'label': 'mock'},
        'season': <String, dynamic>{'month': 1, 'label': 'winter'},
        'best_windows': <String>[],
        'recommended_tactics': <String>[],
        'risk_and_safety': <String>[],
        'evidence': <String>['これはプレースホルダーレスポンスです。'],
        'trace_id': 'mock-trace-id',
        'latency_ms': 100,
      };

      final result = FishingResult.fromJson(mockResponse);
      expect(result.score.value, 50.0);
      expect(result.score.label, 'mock');
      // スコア 50 → stars: 50/20 = 2.5 → 切り捨て 2
      expect(result.score.stars, 2);
    });

    test('推論結果が空の場合（score=0, summary 空）を検出できる', () {
      // home_screen.dart の異常系フォールバック判定と対応するテスト。
      final result = FishingResult.fromJson(<String, dynamic>{
        'summary': '',
        'score': <String, dynamic>{'value': 0.0, 'label': ''},
        'season': <String, dynamic>{'month': 0, 'label': ''},
        'trace_id': '',
        'latency_ms': 0,
      });

      // score.value == 0 かつ summary.isEmpty → UI でフォールバック表示
      expect(result.score.value == 0 && result.summary.isEmpty, isTrue);
    });
  });
}
