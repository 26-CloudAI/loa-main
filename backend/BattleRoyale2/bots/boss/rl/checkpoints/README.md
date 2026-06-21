# BR2 RL 보스 체크포인트

이 디렉토리에 `gen_NNNNN.npz` 형식의 체크포인트가 있으면 `ws_server.py` 가
부팅 시 RL 보스(상) 를 활성화한다. 없으면 `boss_difficulty="hard"` 요청은
자동으로 `medium` 으로 폴백한다.

## 파일 포맷

`.npz` (`np.savez_compressed`) 키:

- `W1` `(80, 256)` float32
- `b1` `(256,)` float32
- `W2` `(256, 128)` float32
- `b2` `(128,)` float32
- `W3` `(128, 20)` float32
- `b3` `(20,)` float32
- `meta` object array (`{generation, win_rate, step_count, ...}`)

상세는 `../network.py` 의 `QNetwork.save / load` 참조.

## 명명 규칙

`gen_00012.npz` (5자리 zero-padded generation). `league_index.json` 의
`filename` 필드와 매칭.

## 학습 산출물 → 체크포인트 변환

학습 환경(Phase 4 후속) 가 결정되면:

```
backend/BattleRoyale2/scripts/tools/convert_torch_to_numpy_br2.py
```

가 PyTorch state_dict → 이 디렉토리의 `.npz` 로 변환.
