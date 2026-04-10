import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class FishingResult {
  FishingResult({
    required this.advice,
    required this.score,
    required this.raw,
  });

  final String advice;
  final int score;
  final Map<String, dynamic> raw;

  factory FishingResult.fromJson(Map<String, dynamic> json) {
    return FishingResult(
      advice: json['advice'] as String? ?? '',
      score: (json['score'] as num?)?.toInt() ?? 0,
      raw: json,
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
      final body = jsonDecode(response.body) as Map<String, dynamic>;
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
