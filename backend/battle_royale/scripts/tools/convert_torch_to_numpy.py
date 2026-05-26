"""
torch checkpoint → numpy weights 변환기
=========================================

학습기 (train_boss_parallel.py) 가 만드는 `trained_weights_torch.pt` 를
서빙용 `trained_weights.json` (numpy json v4) 으로 변환한다.

배경:
  - 학습용 RLBossBotTorch  : 43 → 256 → 128 → 19 (PyTorch Sequential)
  - 서빙용 RLBossBot(numpy): 동일 구조 (B 트랙 통합)
  - PyTorch Linear 의 weight shape 는 (out, in), numpy 는 (in, out) → transpose 필요

키 매핑:
  torch state_dict           numpy json
  ────────────────────────   ──────────────────────
  net.0.weight (256, 43)  →  online.W1 (43, 256)   [transpose]
  net.0.bias   (256,)     →  online.b1 (256,)
  net.2.weight (128, 256) →  online.W2 (256, 128)  [transpose]
  net.2.bias   (128,)     →  online.b2 (128,)
  net.4.weight (19, 128)  →  online.W3 (128, 19)   [transpose]
  net.4.bias   (19,)      →  online.b3 (19,)
  (target 도 동일)

사용:
  python3 convert_torch_to_numpy.py                                    # 기본 경로
  python3 convert_torch_to_numpy.py --in /tmp/trained.pt --out /tmp/out.json
  python3 convert_torch_to_numpy.py --check                            # 변환만 검증, 저장 X

torch 미설치 환경에선 import 실패. 학습 VM 에서만 호출 가정.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("convert_torch_to_numpy")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_TORCH_IN  = _PROJECT_ROOT / "bots" / "boss" / "trained_weights_torch.pt"
DEFAULT_NUMPY_OUT = _PROJECT_ROOT / "bots" / "boss" / "trained_weights.json"

# numpy 봇 (rl_boss_bot.py) 의 schema 와 정확히 일치해야 함
EXPECTED_N_FEATURES = 43
EXPECTED_N_HIDDEN1  = 256
EXPECTED_N_HIDDEN2  = 128
EXPECTED_N_ACTIONS  = 19

# torch Sequential 인덱스 (net.{0,2,4}.{weight,bias})
TORCH_LAYER_KEYS = [
    ("net.0.weight", "net.0.bias", "W1", "b1"),
    ("net.2.weight", "net.2.bias", "W2", "b2"),
    ("net.4.weight", "net.4.bias", "W3", "b3"),
]


def _state_dict_to_numpy_dict(state_dict: dict) -> dict:
    """torch state_dict → numpy 봇 형식 dict (W1/b1/W2/b2/W3/b3, 모두 list)."""
    import torch
    out: dict[str, list] = {}
    for w_key, b_key, np_w, np_b in TORCH_LAYER_KEYS:
        if w_key not in state_dict or b_key not in state_dict:
            raise KeyError(f"state_dict 에 {w_key} 또는 {b_key} 없음")
        w_tensor = state_dict[w_key]
        b_tensor = state_dict[b_key]
        # torch Linear weight: (out, in) → numpy 봇은 (in, out)
        w_np = w_tensor.detach().cpu().numpy().T  # transpose
        b_np = b_tensor.detach().cpu().numpy()
        out[np_w] = w_np.astype("float32").tolist()
        out[np_b] = b_np.astype("float32").tolist()
    return out


def _validate_shapes(np_dict: dict, name: str) -> None:
    """변환된 numpy dict 의 shape 검증."""
    import numpy as np
    expected = {
        "W1": (EXPECTED_N_FEATURES, EXPECTED_N_HIDDEN1),
        "b1": (EXPECTED_N_HIDDEN1,),
        "W2": (EXPECTED_N_HIDDEN1, EXPECTED_N_HIDDEN2),
        "b2": (EXPECTED_N_HIDDEN2,),
        "W3": (EXPECTED_N_HIDDEN2, EXPECTED_N_ACTIONS),
        "b3": (EXPECTED_N_ACTIONS,),
    }
    for k, exp_shape in expected.items():
        arr = np.asarray(np_dict[k])
        if arr.shape != exp_shape:
            raise ValueError(
                f"{name}.{k}: shape {arr.shape} != expected {exp_shape}"
            )


def convert(in_path: Path, out_path: Optional[Path] = None,
            *, dry_run: bool = False) -> dict:
    """
    torch.pt → numpy.json 변환.

    Args:
      in_path: torch checkpoint 파일 경로
      out_path: numpy json 출력 경로 (dry_run=True 면 무시)
      dry_run: True 면 변환 + 검증만, 저장 안 함

    Returns:
      변환된 numpy json dict.
    """
    import torch

    if not in_path.exists():
        raise FileNotFoundError(f"torch checkpoint 없음: {in_path}")

    logger.info("torch checkpoint 로드: %s", in_path)
    ckpt = torch.load(in_path, map_location="cpu", weights_only=True)

    # 메타 검증
    if ckpt.get("version") != 4:
        raise ValueError(
            f"torch checkpoint version={ckpt.get('version')} 미지원 (v4 필요)"
        )
    if ckpt.get("n_features")  != EXPECTED_N_FEATURES \
            or ckpt.get("n_hidden1") != EXPECTED_N_HIDDEN1 \
            or ckpt.get("n_hidden2") != EXPECTED_N_HIDDEN2 \
            or ckpt.get("n_actions") != EXPECTED_N_ACTIONS:
        raise ValueError(
            "torch checkpoint hyperparams 불일치: "
            f"n_features={ckpt.get('n_features')}, n_hidden1={ckpt.get('n_hidden1')}, "
            f"n_hidden2={ckpt.get('n_hidden2')}, n_actions={ckpt.get('n_actions')} "
            f"(기대 {EXPECTED_N_FEATURES}/{EXPECTED_N_HIDDEN1}/"
            f"{EXPECTED_N_HIDDEN2}/{EXPECTED_N_ACTIONS})"
        )

    online_np = _state_dict_to_numpy_dict(ckpt["online"])
    target_np = _state_dict_to_numpy_dict(ckpt["target"])

    _validate_shapes(online_np, "online")
    _validate_shapes(target_np, "target")

    numpy_json = {
        "version":       4,
        "n_features":    EXPECTED_N_FEATURES,
        "n_hidden1":     EXPECTED_N_HIDDEN1,
        "n_hidden2":     EXPECTED_N_HIDDEN2,
        "n_actions":     EXPECTED_N_ACTIONS,
        "step_count":    int(ckpt.get("step_count", 0)),
        "episode_count": int(ckpt.get("episode_count", 0)),
        "epsilon":       float(ckpt.get("epsilon", 0.05)),
        "online":        online_np,
        "target":        target_np,
        # 학습 buffer 는 변환하지 않음 (서빙 봇은 추론 전용)
        "buffer":        [],
        # 변환 추적 메타
        "converted_from": "trained_weights_torch.pt",
    }

    if dry_run:
        logger.info("dry-run: 변환만 수행, 저장 안 함")
        return numpy_json

    # Atomic write
    out_path = out_path or DEFAULT_NUMPY_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=out_path.name + ".",
        suffix=".tmp",
        dir=str(out_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(numpy_json, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, out_path)
        logger.info(
            "변환 완료: %s → %s (gen=%d, step=%d, eps=%.3f)",
            in_path, out_path,
            numpy_json["episode_count"], numpy_json["step_count"], numpy_json["epsilon"],
        )
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return numpy_json


def main() -> int:
    p = argparse.ArgumentParser(
        description="torch checkpoint → numpy weights 변환기",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--in",  dest="in_path",  type=str, default=str(DEFAULT_TORCH_IN),
                   help="입력 torch.pt 경로")
    p.add_argument("--out", dest="out_path", type=str, default=str(DEFAULT_NUMPY_OUT),
                   help="출력 numpy.json 경로")
    p.add_argument("--check", action="store_true",
                   help="변환·검증만 수행, 저장 안 함 (dry-run)")
    p.add_argument("--upload-gcs", action="store_true",
                   help="변환 후 numpy.json 을 GCS에 업로드 "
                        "(BOSS_WEIGHTS_GCS_URI 필요)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        convert(
            in_path  = Path(args.in_path),
            out_path = Path(args.out_path),
            dry_run  = args.check,
        )
    except Exception as exc:
        logger.error("변환 실패: %s", exc)
        return 1

    if args.upload_gcs and not args.check:
        try:
            # battle_royale 디렉토리를 PYTHONPATH 에 추가해서 src.arena.gcs_weights import
            sys.path.insert(0, str(_PROJECT_ROOT))
            from src.arena import gcs_weights  # type: ignore
            if gcs_weights.enabled():
                # numpy.json 은 weights 와 같은 디렉토리에 업로드
                # gcs_weights.upload 는 BOSS_WEIGHTS_GCS_URI 기준 같은 파일을 덮어쓰므로,
                # 별도 sibling URI 사용
                out_uri = gcs_weights._sibling_uri(Path(args.out_path).name)
                if out_uri:
                    ok = gcs_weights.upload(Path(args.out_path), gcs_uri=out_uri)
                    print(f"  GCS 업로드 ({out_uri}): {'성공' if ok else '실패'}")
                else:
                    print("  BOSS_WEIGHTS_GCS_URI 미설정 — GCS 업로드 skip")
            else:
                print("  GCS 비활성화 — GCS 업로드 skip")
        except Exception as exc:
            logger.warning("GCS 업로드 실패: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
