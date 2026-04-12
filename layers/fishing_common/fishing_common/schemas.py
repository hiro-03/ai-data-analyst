"""
Pydantic v2 共通スキーマ定義。

- FishingRequest         : POST /fishing の入力バリデーション用スキーマ
- FishingAdviceResponse  : Bedrock エージェント（InvokeAgent）出力の検証用スキーマ

FishingAdviceResponse は推論 Lambda の内部でも使用する。Bedrock が返す JSON が
このスキーマを満たさない場合（スコアの範囲外、必須フィールド欠損等）は
ValidationError を送出し、Step Functions の実行を FAILED にすることで
品質劣化のサイレント通過を防止する。
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class FishingRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="緯度（-90 〜 90）")
    lon: float = Field(..., ge=-180, le=180, description="経度（-180 〜 180）")
    target_species: Optional[str] = None
    spot_type: Optional[str] = None
    start_at: Optional[str] = None

    model_config = {"extra": "ignore"}


class ScoreDetail(BaseModel):
    value: float = Field(..., ge=0, le=100)
    label: str = ""


class SeasonDetail(BaseModel):
    month: int = Field(..., ge=1, le=12)
    label: str = ""


class FishingAdviceResponse(BaseModel):
    summary: str = ""
    score: ScoreDetail
    season: SeasonDetail
    # 実 API 契約では文字列リストを想定。Flutter 側は List[str] として受け取る。
    best_windows: List[Any] = []
    recommended_tactics: List[Any] = []
    risk_and_safety: List[Any] = []
    evidence: List[Any] = []
    # 実釣向けの短文（日本語）。潮・魚種・釣り場種別に応じて推論する。
    depth_advice: str = Field(
        default="",
        description="狙う水層・深さの目安（例: 表層〜中層 2〜5m）",
    )
    casting_advice: str = Field(
        default="",
        description="投げの目安（堤防なら足元〜何 m 先など）。岸種別で変える。",
    )

    model_config = {"extra": "ignore"}
