import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../services/fishing_api_service.dart';

// 魚種コードと表示名の対応リスト。
// バックエンドの FishingRequest.target_species が受け付ける値（任意の文字列可）。
const _speciesList = [
  'aji',
  'iwashi',
  'saba',
  'buri',
  'tai',
  'kisu',
  'mebaru',
  'chinu',
  'kurodai',
  'hirame',
  'suzuki',
  'kasago',
  'madai',
  'souda',
  'isaki',
  'ika',
  'tachiuo',
];
const _speciesJa = [
  'アジ',
  'イワシ',
  'サバ',
  'ブリ',
  'タイ',
  'キス',
  'メバル',
  'チヌ',
  'クロダイ',
  'ヒラメ',
  'スズキ',
  'カサゴ',
  'マダイ',
  'ソウダガツオ',
  'イサキ',
  'イカ',
  'タチウオ',
];

// 釣り場種別コードと表示名の対応リスト。
// バックエンドの FishingRequest.spot_type が受け付ける値を使用する。
const _spotList = ['harbor', 'beach', 'rock', 'offshore', 'river'];
const _spotsJa = ['堤防', '砂浜', '磯', '沖合', '川'];

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.idToken});
  final String idToken;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = FishingApiService();
  final _mapController = MapController();

  LatLng _selected = const LatLng(35.681, 139.767);
  // _speciesList / _spotList と名前が衝突しないよう "_selected" プレフィックスを付与。
  String _selectedSpecies = 'aji';
  String _selectedSpot = 'harbor';
  bool _loading = false;
  FishingResult? _result;
  String? _error;

  Future<void> _fetch() async {
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final r = await _api.getFishingAdvice(
        idToken: widget.idToken,
        lat: _selected.latitude,
        lon: _selected.longitude,
        targetSpecies: _selectedSpecies,
        spotType: _selectedSpot,
      );
      setState(() => _result = r);
    } on FishingApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = '通信エラー: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A1628),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1F3C),
        foregroundColor: Colors.white,
        title: const Row(
          children: [
            Icon(Icons.phishing, color: Color(0xFF00BCD4)),
            SizedBox(width: 8),
            Text('AI 釣りアドバイザー', style: TextStyle(fontSize: 18)),
          ],
        ),
        elevation: 0,
      ),
      body: Column(
        children: [
          // 地図エリア: タップで釣り場を選択
          Expanded(
            flex: 5,
            child: Stack(
              children: [
                FlutterMap(
                  mapController: _mapController,
                  options: MapOptions(
                    initialCenter: _selected,
                    initialZoom: 10,
                    onTap: (_, point) => setState(() => _selected = point),
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.example.fishing_app',
                    ),
                    MarkerLayer(
                      markers: [
                        Marker(
                          point: _selected,
                          width: 48,
                          height: 48,
                          child: const Icon(
                            Icons.location_pin,
                            color: Color(0xFF00BCD4),
                            size: 48,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                // 現在の選択座標表示
                Positioned(
                  top: 8,
                  left: 8,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      // withOpacity は deprecated のため withValues を使用。
                      color: Colors.black.withValues(alpha: 0.65),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '📍 ${_selected.latitude.toStringAsFixed(4)}, '
                      '${_selected.longitude.toStringAsFixed(4)}',
                      style:
                          const TextStyle(color: Colors.white, fontSize: 12),
                    ),
                  ),
                ),
                // 操作ガイド
                Positioned(
                  top: 8,
                  right: 8,
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.5),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Text(
                      '地図をタップして釣り場を選択',
                      style: TextStyle(color: Colors.white70, fontSize: 11),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // 条件選択パネル
          Container(
            color: const Color(0xFF0D1F3C),
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: _dropdown<String>(
                    label: '魚種',
                    value: _selectedSpecies,
                    // _speciesList（トップレベル const List）を参照する。
                    items: List.generate(
                      _speciesList.length,
                      (i) => DropdownMenuItem(
                        value: _speciesList[i],
                        child: Text(_speciesJa[i]),
                      ),
                    ),
                    onChanged: (v) => setState(() => _selectedSpecies = v!),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _dropdown<String>(
                    label: '釣り場',
                    value: _selectedSpot,
                    items: List.generate(
                      _spotList.length,
                      (i) => DropdownMenuItem(
                        value: _spotList[i],
                        child: Text(_spotsJa[i]),
                      ),
                    ),
                    onChanged: (v) => setState(() => _selectedSpot = v!),
                  ),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: _loading ? null : _fetch,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF00BCD4),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 20, vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('調べる'),
                ),
              ],
            ),
          ),

          // 結果表示パネル
          Expanded(
            flex: 3,
            child: _buildResultPanel(),
          ),
        ],
      ),
    );
  }

  Widget _buildResultPanel() {
    // エラー表示（オフライン・API エラー等）
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.wifi_off, color: Colors.redAccent, size: 36),
              const SizedBox(height: 12),
              Text(
                _error!,
                style:
                    const TextStyle(color: Colors.redAccent, fontSize: 13),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              // 釣り場（屋外・モバイル回線）での利用を考慮したフォローメッセージ。
              const Text(
                '通信状況を確認してから再度お試しください',
                style: TextStyle(color: Colors.white38, fontSize: 11),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    // 未取得時のプレースホルダー
    if (_result == null) {
      return const Center(
        child: Text(
          '地図をタップして釣り場を選び、「調べる」を押してください',
          style: TextStyle(color: Colors.white38, fontSize: 13),
          textAlign: TextAlign.center,
        ),
      );
    }

    final r = _result!;

    // Bedrock 推論結果が空・非正規の場合のフォールバック表示。
    // score.value == 0 かつ summary が空の場合は推論失敗と判定する。
    if (r.score.value == 0 && r.summary.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'アドバイスを取得できませんでした。\n時間をおいて再度お試しください。',
            style: TextStyle(color: Colors.white38, fontSize: 13),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    // score.value（0〜100）を星数（0〜5）に変換。FishingScore.stars を使用。
    final starCount = r.score.stars;
    final stars = '★' * starCount + '☆' * (5 - starCount);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // スコアと星評価
          Row(
            children: [
              Text(
                // バックエンド: score.value（float）を整数表示。
                'スコア: ${r.score.value.toInt()}/100',
                style: const TextStyle(
                  color: Color(0xFF00BCD4),
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(width: 12),
              Text(stars,
                  style:
                      const TextStyle(color: Colors.amber, fontSize: 18)),
            ],
          ),
          const SizedBox(height: 4),
          // レイテンシとトレース ID（デバッグ・透明性の提示）
          Text(
            '${r.latencyMs}ms  |  '
            'trace: ${r.traceId.length >= 8 ? r.traceId.substring(0, 8) : r.traceId}...',
            style: const TextStyle(color: Colors.white24, fontSize: 10),
          ),
          const SizedBox(height: 10),
          // アドバイス本文（バックエンド: summary フィールド）
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF162032),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              r.summary.isEmpty ? '（アドバイスなし）' : r.summary,
              style: const TextStyle(
                  color: Colors.white, fontSize: 14, height: 1.6),
            ),
          ),
          // 狙いの深さ・水層（バックエンド: depth_advice）
          if (r.depthAdvice.isNotEmpty) ...[
            const SizedBox(height: 10),
            _adviceSubCard(
              icon: Icons.vertical_align_center,
              title: '狙いの深さ・水層',
              body: r.depthAdvice,
            ),
          ],
          // 投げの目安（バックエンド: casting_advice）
          if (r.castingAdvice.isNotEmpty) ...[
            const SizedBox(height: 8),
            _adviceSubCard(
              icon: Icons.outbond,
              title: '投げの目安',
              body: r.castingAdvice,
            ),
          ],
          // 推奨釣り時間帯
          if (r.bestWindows.isNotEmpty) ...[
            const SizedBox(height: 8),
            _infoChips('推奨時間帯', r.bestWindows),
          ],
          // 推奨タクティクス
          if (r.recommendedTactics.isNotEmpty) ...[
            const SizedBox(height: 4),
            _infoChips('タクティクス', r.recommendedTactics),
          ],
          // リスク・安全情報（屋外・海上利用に特に重要）
          if (r.riskAndSafety.isNotEmpty) ...[
            const SizedBox(height: 4),
            _infoChips('⚠ リスク', r.riskAndSafety,
                color: Colors.orangeAccent),
          ],
        ],
      ),
    );
  }

  /// 深さ・投げ幅などサブカード表示。
  Widget _adviceSubCard({
    required IconData icon,
    required String title,
    required String body,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2838),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF00BCD4).withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: const Color(0xFF00BCD4), size: 18),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  color: Color(0xFF00BCD4),
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            body,
            style: const TextStyle(color: Colors.white70, fontSize: 13, height: 1.5),
          ),
        ],
      ),
    );
  }

  /// ラベル付きチップ一覧ウィジェット。
  Widget _infoChips(String label, List<String> items, {Color? color}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: TextStyle(
                color: color ?? Colors.white60, fontSize: 11)),
        const SizedBox(height: 4),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: items
              .map((e) => Chip(
                    label: Text(e,
                        style: const TextStyle(fontSize: 11)),
                    backgroundColor: const Color(0xFF162032),
                    labelStyle:
                        TextStyle(color: color ?? Colors.white70),
                    padding: EdgeInsets.zero,
                    materialTapTargetSize:
                        MaterialTapTargetSize.shrinkWrap,
                  ))
              .toList(),
        ),
      ],
    );
  }

  Widget _dropdown<T>({
    required String label,
    required T value,
    required List<DropdownMenuItem<T>> items,
    required ValueChanged<T?> onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label,
            style:
                const TextStyle(color: Colors.white60, fontSize: 11)),
        const SizedBox(height: 4),
        DropdownButtonFormField<T>(
          value: value,
          items: items,
          onChanged: onChanged,
          dropdownColor: const Color(0xFF162032),
          style: const TextStyle(color: Colors.white),
          decoration: InputDecoration(
            filled: true,
            fillColor: const Color(0xFF162032),
            contentPadding: const EdgeInsets.symmetric(
                horizontal: 12, vertical: 8),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide.none,
            ),
          ),
        ),
      ],
    );
  }
}
