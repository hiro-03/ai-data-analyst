import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../services/fishing_api_service.dart';

const _species = ['aji', 'iwashi', 'saba', 'buri', 'tai', 'kisu'];
const _speciesJa = ['アジ', 'イワシ', 'サバ', 'ブリ', 'タイ', 'キス'];
const _spots = ['harbor', 'beach', 'rock', 'offshore', 'river'];
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
  String _species = 'aji';
  String _spot = 'harbor';
  bool _loading = false;
  FishingResult? _result;
  String? _error;

  Future<void> _fetch() async {
    setState(() { _loading = true; _error = null; _result = null; });
    try {
      final r = await _api.getFishingAdvice(
        idToken: widget.idToken,
        lat: _selected.latitude,
        lon: _selected.longitude,
        targetSpecies: _species,
        spotType: _spot,
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
          // 地図
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
                Positioned(
                  top: 8,
                  left: 8,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.65),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '📍 ${_selected.latitude.toStringAsFixed(4)}, '
                      '${_selected.longitude.toStringAsFixed(4)}',
                      style: const TextStyle(color: Colors.white, fontSize: 12),
                    ),
                  ),
                ),
                Positioned(
                  top: 8,
                  right: 8,
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.5),
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

          // 条件パネル
          Container(
            color: const Color(0xFF0D1F3C),
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Row(
              children: [
                Expanded(child: _dropdown(
                  label: '魚種',
                  value: _species,
                  items: List.generate(_species.length,
                      (i) => DropdownMenuItem(value: _species[i], child: Text(_speciesJa[i]))),
                  onChanged: (v) => setState(() => _species = v!),
                )),
                const SizedBox(width: 12),
                Expanded(child: _dropdown(
                  label: '釣り場',
                  value: _spot,
                  items: List.generate(_spots.length,
                      (i) => DropdownMenuItem(value: _spots[i], child: Text(_spotsJa[i]))),
                  onChanged: (v) => setState(() => _spot = v!),
                )),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: _loading ? null : _fetch,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF00BCD4),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('調べる'),
                ),
              ],
            ),
          ),

          // 結果パネル
          Expanded(
            flex: 3,
            child: _buildResultPanel(),
          ),
        ],
      ),
    );
  }

  Widget _buildResultPanel() {
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(_error!, style: const TextStyle(color: Colors.redAccent)),
        ),
      );
    }

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
    final stars = '★' * (r.score ~/ 20) + '☆' * (5 - r.score ~/ 20);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'スコア: ${r.score}/100',
                style: const TextStyle(
                  color: Color(0xFF00BCD4),
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(width: 12),
              Text(stars, style: const TextStyle(color: Colors.amber, fontSize: 18)),
            ],
          ),
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF162032),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              r.advice.isEmpty ? '（アドバイスなし）' : r.advice,
              style: const TextStyle(color: Colors.white, fontSize: 14, height: 1.6),
            ),
          ),
        ],
      ),
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
        Text(label, style: const TextStyle(color: Colors.white60, fontSize: 11)),
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
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
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
