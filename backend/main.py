"""在线对战记分网站 —— FastAPI 后端。

启动：uvicorn main:app --reload --port 8000
依赖：本地 Redis 已运行（默认 localhost:6379）
"""
import os
import json
import redis
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from redis_store import Store
from scoring import apply_point, undo, reset, court_info

app = FastAPI(title="LetsPlay 对战记分")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
store = Store(r)


def client_ip(req: Request) -> str:
    """取真实客户端 IP（支持反代）。"""
    fwd = req.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else "0.0.0.0"


def me(req: Request) -> dict:
    return store.get_or_create_user(client_ip(req))


# ---------- 身份 ----------
@app.get("/api/me")
def api_me(req: Request):
    return me(req)


# ---------- 对战 ----------
class CreateBody(BaseModel):
    type: str  # singles | doubles
    max_players: int
    total_matches: int
    best_of: int = 3      # 局制：1（一局定胜负）或 3（三局两胜）
    game_point: int = 21  # 单局比分制：15 或 21


@app.post("/api/battle/create")
def create_battle(body: CreateBody, req: Request):
    if body.type not in ("singles", "doubles"):
        raise HTTPException(400, "类型必须为 singles 或 doubles")
    min_p = 2 if body.type == "singles" else 4
    if body.max_players < min_p:
        raise HTTPException(400, f"{body.type} 至少需要 {min_p} 人")
    if body.max_players > 16:
        raise HTTPException(400, "人数上限 16")
    if body.total_matches < 1 or body.total_matches > 60:
        raise HTTPException(400, "场数 1~60")
    if body.best_of not in (1, 3):
        raise HTTPException(400, "局制只能为 1（一局定胜负）或 3（三局两胜）")
    if body.game_point not in (15, 21):
        raise HTTPException(400, "比分制只能为 15 或 21")
    user = me(req)
    battle = store.create_battle(user["id"], body.type, body.max_players, body.total_matches,
                                 body.best_of, body.game_point)
    return {"battle": battle, "user": user, "players": store.get_players(battle["id"])}


@app.get("/api/battle/{bid}")
def get_battle(bid: str, req: Request):
    battle = store.get_battle(bid)
    if not battle:
        raise HTTPException(404, "对战不存在")
    user = me(req)
    players = store.get_players(bid)
    joined = store.is_player(bid, user["id"])
    return {
        "battle": battle,
        "user": user,
        "players": players,
        "joined": joined,
        "is_creator": battle["creator_id"] == user["id"],
    }


@app.post("/api/battle/{bid}/join")
def join_battle(bid: str, req: Request):
    user = me(req)
    try:
        store.join_battle(bid, user["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "user": user, "players": store.get_players(bid)}


@app.post("/api/battle/{bid}/start")
def start_battle(bid: str, req: Request):
    user = me(req)
    try:
        store.start_battle(bid, user["id"])
    except ValueError as e:
        raise HTTPException(403, str(e))
    return {"ok": True, "matches": store.get_matches(bid)}


@app.get("/api/battle/{bid}/matches")
def get_matches(bid: str):
    battle = store.get_battle(bid)
    if not battle:
        raise HTTPException(404, "对战不存在")
    return {
        "battle": battle,
        "matches": store.get_matches(bid),
        "fairness": store.get_fairness(bid),
        "players": store.get_players(bid),
    }


# ---------- 记分 ----------
class ScoreBody(BaseModel):
    action: str  # point_a | point_b | undo | reset


@app.post("/api/match/{mid}/score")
def score(mid: str, body: ScoreBody):
    match = store.get_match(mid)
    if not match:
        raise HTTPException(404, "对战不存在")
    if match["status"] == "done" and body.action != "undo":
        if body.action != "reset":
            raise HTTPException(400, "对战已结束")
    if body.action == "point_a":
        apply_point(match, "a")
    elif body.action == "point_b":
        apply_point(match, "b")
    elif body.action == "undo":
        undo(match)
    elif body.action == "reset":
        reset(match)
    else:
        raise HTTPException(400, "未知操作")

    pipe = r.pipeline()
    pipe.hset(f"match:{mid}", mapping={
        "score_a": str(match["score_a"]),
        "score_b": str(match["score_b"]),
        "game_a": str(match["game_a"]),
        "game_b": str(match["game_b"]),
        "server": match["server"],
        "status": match["status"],
        "history": json.dumps(match["history"]),
        "games_detail": json.dumps(match.get("games_detail", [])),
    })
    pipe.execute()
    # 检查是否全部比赛结束 -> 标记 finished 并缩短 TTL，到期 Redis 自动清理
    if match.get("battle_id"):
        store.check_finish_battle(match["battle_id"])
    match["court"] = court_info(match)
    return match


@app.get("/api/match/{mid}")
def get_match(mid: str):
    match = store.get_match(mid)
    if not match:
        raise HTTPException(404, "对战不存在")
    match["court"] = court_info(match)
    return match


@app.get("/api/battle/{bid}/ranking")
def get_ranking(bid: str):
    """计算对战总得分排名：每个玩家在所有比赛的所有小局中得分之和。"""
    battle = store.get_battle(bid)
    if not battle:
        raise HTTPException(404, "对战不存在")
    matches = store.get_matches(bid)
    players = store.get_players(bid)
    players_map = {p["id"]: p for p in players}

    # 累计每个玩家的总得分
    total_points = {}  # uid -> int
    total_games_won = {}  # uid -> int（赢的局数）
    total_matches_won = {}  # uid -> int（赢的比赛数）

    for m in matches:
        team_a = m.get("team_a", [])
        team_b = m.get("team_b", [])

        # 从 games_detail 累计每局得分
        for g in m.get("games_detail", []):
            for uid in team_a:
                total_points[uid] = total_points.get(uid, 0) + g["score_a"]
            for uid in team_b:
                total_points[uid] = total_points.get(uid, 0) + g["score_b"]

        # 当前进行中的局（未记录到 games_detail 的）
        if m["status"] != "done" or not m.get("games_detail"):
            sa, sb = m["score_a"], m["score_b"]
            if sa > 0 or sb > 0:
                for uid in team_a:
                    total_points[uid] = total_points.get(uid, 0) + sa
                for uid in team_b:
                    total_points[uid] = total_points.get(uid, 0) + sb

        # 赢的局数
        for uid in team_a:
            total_games_won[uid] = total_games_won.get(uid, 0) + m["game_a"]
        for uid in team_b:
            total_games_won[uid] = total_games_won.get(uid, 0) + m["game_b"]

        # 赢的比赛数
        if m["status"] == "done":
            winner_team = team_a if m["game_a"] > m["game_b"] else team_b
            for uid in winner_team:
                total_matches_won[uid] = total_matches_won.get(uid, 0) + 1

    # 构建排名列表
    ranking = []
    for uid in total_points:
        p = players_map.get(uid, {"id": uid, "nickname": uid, "avatar": "?"})
        ranking.append({
            "id": uid,
            "nickname": p.get("nickname", uid),
            "avatar": p.get("avatar", "?"),
            "total_points": total_points.get(uid, 0),
            "games_won": total_games_won.get(uid, 0),
            "matches_won": total_matches_won.get(uid, 0),
        })

    # 排序：总得分降序
    ranking.sort(key=lambda x: x["total_points"], reverse=True)

    # 添加排名序号（同分同名次）
    for i, r in enumerate(ranking):
        if i > 0 and r["total_points"] == ranking[i - 1]["total_points"]:
            r["rank"] = ranking[i - 1]["rank"]
        else:
            r["rank"] = i + 1

    return {"battle": battle, "ranking": ranking}


# ---------- 静态前端 ----------
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
FRONTEND_DIR = os.path.abspath(FRONTEND_DIR)


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# 静态资源（css/js）
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/battle.html")
def battle_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "battle.html"))


@app.get("/matches.html")
def matches_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "matches.html"))


@app.get("/watch.html")
def watch_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "watch.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
