"""对战编排：根据单/双打、人数、场数，生成尽量均匀、对手/队友多样的对战列表。

核心目标：
- 人人都能打（出场次数尽量均等）
- 人人都能组到不同的队友（双打时队友组合尽量不重复）
- 对手尽量多样
"""
import random
from itertools import combinations
from typing import List


def generate_matches(players: List[str], match_type: str, num_matches: int, seed: int = None) -> List[dict]:
    """生成对战列表。

    Args:
        players: 玩家 id 列表
        match_type: "singles" | "doubles"
        num_matches: 对战场数
        seed: 随机种子（用于可复现）

    Returns:
        [{"index": 0, "team_a": [pid,...], "team_b": [pid,...]}, ...]
    """
    rng = random.Random(seed)
    players = list(players)
    if len(players) < (2 if match_type == "singles" else 4):
        return []

    if match_type == "singles":
        return _singles(players, num_matches, rng)
    return _doubles(players, num_matches, rng)


def _singles(players, num_matches, rng):
    n = len(players)
    appearances = {p: 0 for p in players}
    opponent = {frozenset((a, b)): 0 for a, b in combinations(players, 2)}
    matches = []

    for i in range(num_matches):
        # 按出场次数升序，次数相同则随机
        pool = sorted(players, key=lambda p: (appearances[p], rng.random()))
        # 在出场最少的若干人中，选一对还没怎么交手过的
        head = pool[: min(n, 6)]
        best, best_score = None, float("inf")
        for a, b in combinations(head, 2):
            s = opponent[frozenset((a, b))] * 10 + appearances[a] + appearances[b]
            if s < best_score:
                best_score, best = s, (a, b)
        a, b = best
        matches.append({"index": i, "team_a": [a], "team_b": [b]})
        appearances[a] += 1
        appearances[b] += 1
        opponent[frozenset((a, b))] += 1

    return matches


def _doubles(players, num_matches, rng):
    n = len(players)
    appearances = {p: 0 for p in players}
    teammate = {frozenset((a, b)): 0 for a, b in combinations(players, 2)}
    opponent = {frozenset((a, b)): 0 for a, b in combinations(players, 2)}
    matches = []

    for i in range(num_matches):
        pool = sorted(players, key=lambda p: (appearances[p], rng.random()))
        # 取出场最少的 4 人参与本场（保证人人能打）
        four = pool[: min(n, 4)]
        if len(four) < 4:
            four = pool[:4]

        # 4 人拆成 2 队，共 3 种拆法，选队友组合最少用的
        best, best_score = None, float("inf")
        for (a, b, c, d) in [(0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)]:
            t1 = frozenset((four[a], four[b]))
            t2 = frozenset((four[c], four[d]))
            s = teammate[t1] * 5 + teammate[t2] * 5
            # 对手重复度也纳入考量
            for x in t1:
                for y in t2:
                    s += opponent[frozenset((x, y))]
            if s < best_score:
                best_score, best = s, (t1, t2)
        t1, t2 = best
        matches.append({
            "index": i,
            "team_a": sorted(t1),
            "team_b": sorted(t2),
        })
        for p in four:
            appearances[p] += 1
        teammate[t1] += 1
        teammate[t2] += 1
        for x in t1:
            for y in t2:
                opponent[frozenset((x, y))] += 1

    return matches


def fairness_report(players, matches, match_type) -> dict:
    """统计每个玩家的出场次数，便于前端展示均匀度。"""
    appearances = {p: 0 for p in players}
    for m in matches:
        for p in m["team_a"] + m["team_b"]:
            if p in appearances:
                appearances[p] += 1
    vals = list(appearances.values())
    if not vals:
        return {"appearances": appearances, "min": 0, "max": 0, "balanced": True}
    return {
        "appearances": appearances,
        "min": min(vals),
        "max": max(vals),
        "balanced": (max(vals) - min(vals)) <= 1,
    }


def generate_free_matches(teams: dict, num_matches: int, seed: int = None) -> list:
    """自由对战：按用户自定义队伍生成对战列表，队伍间两两循环对战。

    Args:
        teams: {"team_0": [uid,...], "team_1": [uid,...], ...}
               每支队伍的人数由前端控制（单打每队 1 人，双打每队 2 人）。
        num_matches: 对战场数
        seed: 随机种子

    Returns:
        [{"index": 0, "team_a": [uids], "team_b": [uids]}, ...]
    """
    rng = random.Random(seed)
    team_ids = sorted(teams.keys())
    if len(team_ids) < 2:
        return []

    # 所有队伍的两两组合，打乱后循环填充到指定场数
    pairs = list(combinations(team_ids, 2))
    rng.shuffle(pairs)

    matches = []
    for i in range(num_matches):
        tid_a, tid_b = pairs[i % len(pairs)]
        matches.append({
            "index": i,
            "team_a": list(teams[tid_a]),
            "team_b": list(teams[tid_b]),
        })
    return matches
