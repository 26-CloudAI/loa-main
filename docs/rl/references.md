# 참고 논문 및 인용 자료

> [README](README.md) · [01-design](01-design.md) · [02-serving](02-serving.md) · [03-infrastructure](03-infrastructure.md) · [04-status](04-status.md) · **references**

본 문서는 BR2 보스 RL 의 코드/설계가 직접 근거로 삼는 강화학습 논문·교과서를 정리한다. 메타데이터(저자/연도/출판처/DOI 또는 arXiv ID)는 표준 인용 형식 — 인용 시 그대로 사용 가능.

---

## 1. 1차 핵심 — 반드시 인용해야 할 것

### 1.1 DQN 본체 — 본 프로젝트 알고리즘의 직접 근거

**Mnih, V., Kavukcuoglu, K., Silver, D., et al. (2015).** Human-level control through deep reinforcement learning. *Nature*, **518**(7540), 529–533.
[DOI: 10.1038/nature14236](https://doi.org/10.1038/nature14236)

→ Experience Replay, Target Network, ε-greedy, end-to-end Q-learning 의 표준 출처. `scripts/train/train_boss_br2.py` 의 거의 모든 구조가 이 논문 기반.

선행본 (arXiv 워크숍, 자주 같이 인용):

**Mnih, V., Kavukcuoglu, K., Silver, D., et al. (2013).** Playing Atari with Deep Reinforcement Learning.
[arXiv:1312.5602](https://arxiv.org/abs/1312.5602)

---

### 1.2 Experience Replay 시초

**Lin, L.-J. (1992).** Self-improving reactive agents based on reinforcement learning, planning and teaching. *Machine Learning*, **8**(3–4), 293–321.
[DOI: 10.1007/BF00992699](https://doi.org/10.1007/BF00992699)

→ Replay buffer 아이디어 원전. DQN 인용 시 같이 묶는 경우 많음. `ReplayBuffer` 클래스의 역사적 근거.

---

### 1.3 Reward Shaping 이론 — 본 프로젝트 보상 설계의 정당화

**Ng, A. Y., Harada, D., & Russell, S. (1999).** Policy invariance under reward transformations: Theory and application to reward shaping. In *Proceedings of the 16th International Conference on Machine Learning (ICML)*, 278–287.
[PDF (Stanford)](http://robotics.stanford.edu/~ang/papers/shaping-icml99.pdf)

→ "어떤 보상 변형이 최적 정책을 보존하는가" 의 이론적 출처. `docs/rl/01-design.md §3` 의 +150/-20/-10 등 dense + terminal 결합 보상 설계를 정당화할 때 인용.

---

### 1.4 RL 일반 교과서 — 기본 개념 (ε-greedy, MDP, TD, Q-learning)

**Sutton, R. S., & Barto, A. G. (2018).** *Reinforcement Learning: An Introduction* (2nd ed.). MIT Press. ISBN 978-0262039246.
[저자 공식 무료 PDF](http://incompleteideas.net/book/the-book.html)

→ ε-greedy 탐험, γ-discounting, Q-learning 정의의 표준 교과서. 기본 용어 정의 인용 시.

---

## 2. 2차 — Self-Play / League / 다대일 학습

### 2.1 AlphaStar — PFSP, League Training (시나리오 mix 의 직접 원전)

**Vinyals, O., Babuschkin, I., Czarnecki, W. M., et al. (2019).** Grandmaster level in StarCraft II using multi-agent reinforcement learning. *Nature*, **575**(7782), 350–354.
[DOI: 10.1038/s41586-019-1724-z](https://doi.org/10.1038/s41586-019-1724-z)

→ **PFSP (Prioritized Fictitious Self-Play)**, **league training** 의 출처. 본 프로젝트 "PFSP-lite" (`SCENARIO_WEIGHTS`, `bots/boss/rl/league.py`) 가 여기서 영감.

---

### 2.2 AlphaGo Zero — pure self-play

**Silver, D., Schrittwieser, J., Simonyan, K., et al. (2017).** Mastering the game of Go without human knowledge. *Nature*, **550**(7676), 354–359.
[DOI: 10.1038/nature24270](https://doi.org/10.1038/nature24270)

→ 자기복제 학습이 강화학습의 강력한 패러다임이라는 사례. `past_opponent.py` (PastBossOpponentBR2 freeze wrapper) 의 의도와 매핑.

---

### 2.3 TD-Gammon — Self-play + NN + RL 의 시초

**Tesauro, G. (1995).** Temporal difference learning and TD-Gammon. *Communications of the ACM*, **38**(3), 58–68.
[DOI: 10.1145/203330.203343](https://doi.org/10.1145/203330.203343)

→ "NN + RL + self-play" 의 최초 성공 사례. 역사 맥락용 짧은 인용에 적합.

---

## 3. 3차 — 대규모 게임 RL · 향후 개선 후보

### 3.1 OpenAI Five (Dota 2)

**Berner, C., Brockman, G., Chan, B., et al. (2019).** Dota 2 with Large Scale Deep Reinforcement Learning.
[arXiv:1912.06680](https://arxiv.org/abs/1912.06680)

→ PPO + self-play 대규모 적용. 본 프로젝트가 향후 PPO 전환을 고려할 때 비교 baseline.

---

### 3.2 PPO — 향후 알고리즘 후보

**Schulman, J., Wolski, F., Dhariwal, P., Radford, A., & Klimov, O. (2017).** Proximal Policy Optimization Algorithms.
[arXiv:1707.06347](https://arxiv.org/abs/1707.06347)

→ [04-status.md §4.3](04-status.md#43-장기-1개월) 의 "PPO/A2C 비교" 후보 알고리즘.

---

### 3.3 Double DQN — DQN overestimation bias 보정 (향후 적용 후보)

**van Hasselt, H., Guez, A., & Silver, D. (2016).** Deep Reinforcement Learning with Double Q-learning. *Proceedings of the AAAI Conference on Artificial Intelligence*, **30**(1).
[arXiv:1509.06461](https://arxiv.org/abs/1509.06461)

→ 본 코드는 단일 Q-net 의 max 를 사용 — 이 논문이 그 bias 를 지적/완화. 학습 안정성 튜닝 시 검토 ([04-status.md §3.1](04-status.md#31-학습-자체)).

---

## 4. 본 프로젝트 ↔ 인용 매핑 표

| 본 프로젝트 항목 | 코드/문서 위치 | 1차 인용 |
|---|---|---|
| DQN, target net, Huber loss | `train_boss_br2.py` `_dqn_update` | Mnih 2015 |
| Experience Replay | `train_boss_br2.py` `ReplayBuffer` | Lin 1992; Mnih 2015 |
| ε-greedy 탐험 | `_select_action` | Sutton & Barto 2018 |
| Terminal + dense reward 결합 | [01-design.md §3](01-design.md#3-보상-설계) | Ng et al. 1999 |
| PFSP-lite 시나리오 mix | `SCENARIO_WEIGHTS`, [01-design.md §4](01-design.md#4-시나리오-mix) | Vinyals 2019 |
| League / past_opponent | `bots/boss/rl/league.py`, `past_opponent.py` | Vinyals 2019; Silver 2017 |
| 향후 PPO 검토 | [04-status.md §4.3](04-status.md#43-장기-1개월) | Schulman 2017; Berner 2019 |
| 향후 Double DQN | [04-status.md §3.1](04-status.md#31-학습-자체) | van Hasselt 2016 |

---

## 5. 인용 시 주의

### 5.1 본 프로젝트 내부 명명 ↔ 논문 용어 구분

| 본 프로젝트 명명 | 정확한 출처 | 인용 시 표기 권장 |
|---|---|---|
| **PFSP-lite** | AlphaStar PFSP 의 단순화 변형 | "AlphaStar 의 PFSP (Vinyals et al., 2019) 를 본 프로젝트에 맞춰 단순화한 변형" |
| **BR2MiniEnv** | OpenAI Gym 인터페이스 *유사* (동일 X) | "Gym-like `reset/step` 패턴" 정도가 정확 |
| **다대일 (1 vs 3)** | Multi-agent RL 의 한 형태 | 별도 multi-agent RL 인용 추가 가능 (Vinyals 2019 가 가장 가까움) |

### 5.2 DQN 인용 시

- "**target network 명시는 2015 Nature**" 가 정본. 2013 arXiv 워크숍 버전엔 target network 미수록.
- 둘 다 인용하는 게 안전: "Mnih et al. (2013, 2015)".

### 5.3 Reward shaping

- Ng et al. 1999 는 *potential-based shaping* 의 정책 불변성을 증명한 논문. 본 프로젝트 보상은 *상태 의존 dense + terminal* 결합으로, 엄밀히는 potential-based 가 아님.
- 정확한 인용: "보상 설계의 일반 원리는 Ng et al. (1999) 의 reward shaping 이론을 참고" 정도. "본 프로젝트가 그 정리를 따른다" 라고 단정하면 부정확.

### 5.4 본 가이드의 학습 결과는 PoC

- `gen_00011.npz` 의 `win_rate20=0.00` 은 [04-status.md §2.2](04-status.md#22-정량-결과-학습-종료-시점) 에 명시. 논문 인용 시 "본 프로젝트는 baseline 구축 단계로, 학습 수렴은 미완 상태" 가 정확한 기술.

---

## 6. 추가 자료 (참고용, 본 코드와 직접 매핑 약함)

- **Lange, S., Gabel, T., & Riedmiller, M. (2012).** Batch Reinforcement Learning. In *Reinforcement Learning: State-of-the-Art*. Springer. — Batch / offline RL 개론.
- **Hessel, M., Modayil, J., van Hasselt, H., et al. (2018).** Rainbow: Combining improvements in Deep Reinforcement Learning. *AAAI*. [arXiv:1710.02298](https://arxiv.org/abs/1710.02298) — DQN 개선 모음 (Double + Dueling + PER + Multi-step + ...).
- **Schaul, T., Quan, J., Antonoglou, I., & Silver, D. (2016).** Prioritized Experience Replay. *ICLR*. [arXiv:1511.05952](https://arxiv.org/abs/1511.05952) — uniform replay 대신 TD-error 기반 우선순위 샘플.

---

## 7. 변경 이력

- **2026-06-05** — 초안.

---

← [README](README.md)
