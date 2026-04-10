// 基本的な Flutter ウィジェットテストです。
//
// テストでウィジェットを操作するには flutter_test の WidgetTester を使います。
// 例: タップ・スクロール、子ウィジェットの検索、テキストやプロパティの検証。

import 'package:flutter_test/flutter_test.dart';

import 'package:fishing_app/main.dart';

void main() {
  testWidgets('App shows login title', (WidgetTester tester) async {
    await tester.pumpWidget(const FishingApp());

    expect(find.text('AI 釣りアドバイザー'), findsOneWidget);
  });
}
