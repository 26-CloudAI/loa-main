"""유저 봇 작성 예시 (프론트 코드 에디터 기본값으로도 사용).

InProcessBot2 의 exec 네임스페이스에 `BattleRoyale2DBot` 가 주입되므로 import 불필요.
허용 import: math, random, json, collections, heapq, itertools.

state / action 스키마는 GAME_RULES.md §9 / PROTOCOL.md 참조.
- state["self"]: pos/hp/max_hp/atk/def/speed/attack_cd/dash_cd/guard_cd/has_potion/has_ranged/guarding ...
- state["vision"]: enemies[], items[], nodes[](코인), chests[], projectiles[]
- state["zone"]: active/center/radius/damage/phase (+ target_center/target_radius/target_eta 활성 시)
- 반환 action: move_dir[x,y](길이 0~1) / aim_dir[x,y] / attack / guard / dash / pickup / use_potion
"""
import math


class Bot(BattleRoyale2DBot):
    def choose_spawn(self, map_info):
        # 희귀 코인 클러스터 근처에서 시작 (없으면 상자 클러스터, 둘 다 없으면 랜덤)
        rc = map_info.get("rare_clusters") or map_info.get("chest_clusters") or []
        if rc:
            return (rc[0][0], rc[0][1])
        return None

    def get_action(self, state):
        me = state["self"]
        x, y = me["pos"]
        vision = state["vision"]
        zone = state.get("zone", {})
        action = {
            "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
            "attack": False, "guard": False, "dash": False,
            "pickup": False, "use_potion": False,
        }

        # 1) HP 낮고 포션 보유 → 사용
        if me.get("has_potion") and me["hp"] < 80:
            action["use_potion"] = True

        # 2) 자기장 밖이면 중심 방향으로 이동
        if zone.get("active") and zone.get("damage", 0) > 0:
            cx, cy = zone["center"]
            dx, dy = cx - x, cy - y
            d = math.hypot(dx, dy)
            if d > zone.get("radius", 0):
                action["move_dir"] = [dx / d, dy / d]
                action["aim_dir"] = [dx / d, dy / d]
                if me.get("dash_cd", 1) <= 0:
                    action["dash"] = True
                return action

        # 3) 시야 내 가까운 적 → 사거리 안이면 공격, 아니면 접근
        enemies = vision.get("enemies", [])
        if enemies:
            e = min(enemies, key=lambda en: (en["pos"][0] - x) ** 2 + (en["pos"][1] - y) ** 2)
            dx, dy = e["pos"][0] - x, e["pos"][1] - y
            d = math.hypot(dx, dy) or 1.0
            action["aim_dir"] = [dx / d, dy / d]
            if d <= 60:
                action["attack"] = True
            else:
                action["move_dir"] = [dx / d, dy / d]
            return action

        # 4) 시야 내 코인 채집 (희귀 우선)
        nodes = vision.get("nodes", [])
        if nodes:
            rare = [n for n in nodes if n.get("rare")]
            pool = rare if rare else nodes
            n = min(pool, key=lambda nd: (nd["pos"][0] - x) ** 2 + (nd["pos"][1] - y) ** 2)
            dx, dy = n["pos"][0] - x, n["pos"][1] - y
            d = math.hypot(dx, dy) or 1.0
            action["move_dir"] = [dx / d, dy / d]
            action["aim_dir"] = [dx / d, dy / d]

        return action
