"""羽毛球记分逻辑：每球得分制，支持可配置局制与比分制。

规则：
- 每球得分制（rally scoring）：每个回合都得分，赢球方下一拍发球
- 单局到达 game_point 分，需领先 2 分获胜；game_point+9:game_point+9 时先到 game_point+10 分获胜
- best_of 局制：1（一局定胜负）或 3（三局两胜）
- 发球方与发球区位（偶数分右区，奇数分左区）

match 字典中读取以下配置（缺省则用默认 21 分三局两胜）：
- game_point: 单局获胜分数（默认 21）
- best_of: 局制（1 或 3，默认 3）；需赢 (best_of//2 + 1) 局
"""
import json

DEFAULT_GAME_POINT = 21
WIN_MARGIN = 2
DEFAULT_BEST_OF = 3


def _game_point(match: dict) -> int:
    return int(match.get("game_point", DEFAULT_GAME_POINT))


def _games_to_win(match: dict) -> int:
    best_of = int(match.get("best_of", DEFAULT_BEST_OF))
    return best_of // 2 + 1


def _cap_point(match: dict) -> int:
    return _game_point(match) + 10


def snapshot(match: dict) -> dict:
    """记录当前状态快照，供 undo 使用。"""
    return {
        "score_a": match["score_a"],
        "score_b": match["score_b"],
        "game_a": match["game_a"],
        "game_b": match["game_b"],
        "server": match["server"],
        "status": match["status"],
        "games_detail": list(match.get("games_detail", [])),
    }


def apply_point(match: dict, side: str) -> dict:
    """side = "a" | "b"，表示该回合得分方。"""
    if match["status"] == "done":
        return match

    gp = _game_point(match)
    cap = _cap_point(match)
    games_to_win = _games_to_win(match)

    # 入栈快照
    match["history"].append(snapshot(match))

    match[f"score_{side}"] += 1
    match["server"] = side  # 赢球方发球

    sa, sb = match["score_a"], match["score_b"]
    game_over = False
    if (sa >= gp or sb >= gp) and abs(sa - sb) >= WIN_MARGIN:
        game_over = True
    elif sa >= cap or sb >= cap:
        game_over = True

    if game_over:
        # 记录本局最终得分到 games_detail
        if "games_detail" not in match:
            match["games_detail"] = []
        match["games_detail"].append({"score_a": sa, "score_b": sb})

        if sa > sb:
            match["game_a"] += 1
        else:
            match["game_b"] += 1
        # 判断比赛结束
        if match["game_a"] >= games_to_win or match["game_b"] >= games_to_win:
            match["status"] = "done"
        else:
            # 进入下一局，比分清零；下一局由上一局输方发球
            loser = "b" if sa > sb else "a"
            match["server"] = loser
            match["score_a"] = 0
            match["score_b"] = 0
            match["status"] = "live"
    else:
        match["status"] = "live"

    return match


def undo(match: dict) -> dict:
    if not match["history"]:
        return match
    prev = match["history"].pop()
    match["score_a"] = prev["score_a"]
    match["score_b"] = prev["score_b"]
    match["game_a"] = prev["game_a"]
    match["game_b"] = prev["game_b"]
    match["server"] = prev["server"]
    match["status"] = prev["status"]
    match["games_detail"] = prev.get("games_detail", [])
    return match


def reset(match: dict) -> dict:
    match["score_a"] = 0
    match["score_b"] = 0
    match["game_a"] = 0
    match["game_b"] = 0
    match["server"] = "a"
    match["status"] = "live"
    match["history"] = []
    match["games_detail"] = []
    return match


def court_info(match: dict) -> dict:
    """发球区位：发球方分数为偶数 → 右区，奇数 → 左区。"""
    server = match["server"]
    score = match[f"score_{server}"]
    return {
        "server": server,
        "court": "right" if score % 2 == 0 else "left",
    }
