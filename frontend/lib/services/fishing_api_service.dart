import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

// ─────────────────────────────────────────────────────────────────────────────
// バックエンド（Pydantic）との型契約
//
// このファイルのモデルクラスは、バックエンドの Pydantic スキーマと
// 1 対 1 で対応するよう設計されています。
//
// バックエンド定義:
//   layers/fishing_common/fishing_common/schemas.py
//
// API が返す JSON 構造（FishingAdviceResponse.model_dump() の出力）:
//   {
//     "summary":              String,          // 釣りアドバイス本文
//     "score":                {                // ScoreDetail
//       "value":              0.0–100.0,
//       "label":              String           // "excellent" / "good" / "mock" など
//     },
//     "season":               {                // SeasonDetail
//       "month":              1–12,
//       "label":              "winter|spring|summer|autumn"
//     },
//     "best_windows":         [String],        // 推奨釣り時間帯
//     "recommended_tactics":  [String],        // 推奨タクティクス
//     "risk_and_safety":      [String],        // リスク・安全情報
//     "evidence":             [String],        // 判断根拠
//     "depth_advice":         String,          // 狙う水層・深さの目安
//     "casting_advice":       String,          // 投げの目安（堤防など）
//     // 以下は API プロキシ Lambda が付与するメタ情報
//     "trace_id":             String (UUID),
//     "latency_ms":           int
//   }
//
// スキーマを変更した場合は、バックエンドとフロントエンドを同時に更新してください。
// 型整合は frontend/test/widget_test.dart の FishingResult スキーマ整合テストで保証します。
// ─────────────────────────────────────────────────────────────────────────────

/// スコア詳細（バックエンド ScoreDetail に対応）。
class FishingScore {
  const FishingScore({required this.value, required this.label});

  /// 釣果スコア（0.0 〜 100.0）。バックエンド: `score.value`。
  final double value;

  /// スコアのラベル（例: "excellent", "good", "mock"）。バックエンド: `score.label`。
  final String label;

  factory FishingScore.fromJson(Map<String, dynamic> json) {
    return FishingScore(
      value: (json['value'] as num? ?? 0).toDouble(),
      label: json['label'] as String? ?? '',
    );
  }

  /// score.value（0〜100）を 0〜5 の星数に変換するユーティリティ。
  int get stars => (value / 20).floor().clamp(0, 5);
}

/// 季節情報（バックエンド SeasonDetail に対応）。
class FishingSeason {
  const FishingSeason({required this.month, required this.label});

  /// 月（1〜12）。バックエンド: `season.month`。
  final int month;

  /// 季節ラベル（"winter" / "spring" / "summer" / "autumn"）。バックエンド: `season.label`。
  final String label;

  factory FishingSeason.fromJson(Map<String, dynamic> json) {
    return FishingSeason(
      month: json['month'] as int? ?? 0,
      label: json['label'] as String? ?? '',
    );
  }
}

/// 釣り推論 API のレスポンス全体（バックエンド FishingAdviceResponse に対応）。
///
/// バックエンド側のスキーマ定義:
///   layers/fishing_common/fishing_common/schemas.py#FishingAdviceResponse
class FishingResult {
  const FishingResult({
    required this.summary,
    required this.score,
    required this.season,
    required this.bestWindows,
    required this.recommendedTactics,
    required this.riskAndSafety,
    required this.evidence,
    required this.depthAdvice,
    required this.castingAdvice,
    required this.traceId,
    required this.latencyMs,
  });

  /// 釣りアドバイスの本文。バックエンド: `summary`（旧 `advice` ではないことに注意）。
  final String summary;

  /// 釣果スコア。バックエンド: `score`（Map: value / label）。
  final FishingScore score;

  /// 季節情報。バックエンド: `season`（Map: month / label）。
  final FishingSeason season;

  /// 推奨釣り時間帯。バックエンド: `best_windows`。
  final List<String> bestWindows;

  /// 推奨タクティクス。バックエンド: `recommended_tactics`。
  final List<String> recommendedTactics;

  /// リスク・安全情報。バックエンド: `risk_and_safety`。
  final List<String> riskAndSafety;

  /// 判断根拠。バックエンド: `evidence`。
  final List<String> evidence;

  /// 狙う水層・深さの目安。バックエンド: `depth_advice`。
  final String depthAdvice;

  /// 投げの目安（堤防の距離感など）。バックエンド: `casting_advice`。
  final String castingAdvice;

  /// エンドツーエンド追跡 ID（API プロキシが付与）。バックエンド: `trace_id`。
  final String traceId;

  /// API 全体のレイテンシ（ミリ秒）（API プロキシが付与）。バックエンド: `latency_ms`。
  final int latencyMs;

  factory FishingResult.fromJson(Map<String, dynamic> json) {
    // score・season が Map でない場合は空 Map にフォールバック（防御的パース）。
    final scoreMap = json['score'] is Map<String, dynamic>
        ? json['score'] as Map<String, dynamic>
        : <String, dynamic>{};
    final seasonMap = json['season'] is Map<String, dynamic>
        ? json['season'] as Map<String, dynamic>
        : <String, dynamic>{};

    // リストフィールドは要素を String に変換して取り出す。
    List<String> toStringList(dynamic v) =>
        v is List ? v.map((e) => e.toString()).toList() : const [];

    return FishingResult(
      summary: json['summary'] as String? ?? '',
      score: FishingScore.fromJson(scoreMap),
      season: FishingSeason.fromJson(seasonMap),
      bestWindows: toStringList(json['best_windows']),
      recommendedTactics: toStringList(json['recommended_tactics']),
      riskAndSafety: toStringList(json['risk_and_safety']),
      evidence: toStringList(json['evidence']),
      depthAdvice: json['depth_advice'] as String? ?? '',
      castingAdvice: json['casting_advice'] as String? ?? '',
      traceId: json['trace_id'] as String? ?? '',
      latencyMs: json['latency_ms'] as int? ?? 0,
    );
  }
}

/// 釣り推論 API を呼び出すサービス。
class FishingApiService {
  Future<FishingResult> getFishingAdvice({
    required String idToken,
    required double lat,
    required double lon,
    required String targetSpecies,
    required String spotType,
  }) async {
    final response = await http.post(
      Uri.parse(AppConfig.fishingApiUrl),
      headers: {
        'Content-Type': 'application/json',
        // Cognito ID トークンを Authorization ヘッダーで渡す（Bearer なし）。
        // API Gateway の Cognito オーソライザーがこの形式を要求する。
        'Authorization': idToken,
      },
      body: jsonEncode({
        'lat': lat,
        'lon': lon,
        'target_species': targetSpecies,
        'spot_type': spotType,
      }),
    );

    if (response.statusCode != 200) {
      Map<String, dynamic> body;
      try {
        body = jsonDecode(response.body) as Map<String, dynamic>;
      } catch (_) {
        body = {};
      }
      throw FishingApiException(
        'API エラー ${response.statusCode}: '
        '${body['message'] ?? body['error'] ?? response.body}',
      );
    }

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return FishingResult.fromJson(body);
  }
}

class FishingApiException implements Exception {
  FishingApiException(this.message);
  final String message;

  @override
  String toString() => message;
}
