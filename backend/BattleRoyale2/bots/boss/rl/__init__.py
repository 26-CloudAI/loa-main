"""BR2 강화학습 보스 — 난이도 '상' 인프라.

모듈:
    encoder       : BR2 state → 80-D feature vector
    decoder       : 20 디스크리트 액션 → 7키 BR2 액션 dict
    network       : numpy MLP (inference-only, 옛 RLBossBot 구조)
    inference     : RLBossBR2 (BattleRoyale2DBot 구현, 체크포인트 로드)
    league        : 체크포인트 풀 (recency_bias 0.6, top-12 유지)
    past_opponent : freeze opponent 래퍼

학습 환경(Phase 4 후속) 가 정해지면:
    - train_boss_br2.py : PyTorch 학습 스크립트
    - convert_torch_to_numpy_br2.py : 학습 산출물 → .npz 변환
    - rl/checkpoints/gen_NNNNN.npz : 체크포인트 누적
"""

from .encoder import encode_state, FEATURE_DIM, DEFAULT_MATCH_DURATION
from .decoder import decode_action, encode_action, ACTION_DIM
from .network import QNetwork
from .inference import RLBossBR2, DEFAULT_CHECKPOINT_DIR
from .league import LeagueEntry, LeagueIndex, DEFAULT_LEAGUE_DIR
from .past_opponent import PastBossOpponentBR2

__all__ = [
    "encode_state", "FEATURE_DIM", "DEFAULT_MATCH_DURATION",
    "decode_action", "encode_action", "ACTION_DIM",
    "QNetwork",
    "RLBossBR2", "DEFAULT_CHECKPOINT_DIR",
    "LeagueEntry", "LeagueIndex", "DEFAULT_LEAGUE_DIR",
    "PastBossOpponentBR2",
]
