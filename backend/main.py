"""在线对战记分网站 —— FastAPI 后端。

启动：uvicorn main:app --reload --port 8000
依赖：本地 Redis 已运行（默认 localhost:6379）
"""
import os
import json
import asyncio
import logging
import redis
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from redis_store import Store
from scoring import apply_point, undo, reset, court_info

log = logging.getLogger("letsplay")
# 让 startup/shutdown 里的 log.info 能被写入 letsplay.log（sweeper 启动 / 完成清理）
if not log.handlers:
    log.setLevel(logging.INFO)
    _fh = logging.FileHandler("letsplay.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log.addHandler(_fh)
    log.propagate = False  # 直接写文件，避免与 uvicorn 默认 handler 重复

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


# ---------- 后台过期清理 ----------
SWEEP_INTERVAL = int(os.getenv("SWEEP_INTERVAL", "300"))  # 默认 5 分钟一次


async def _sweeper_loop():
    """定期扫描过期对战，waiting>4h / ongoing>8h 自动 finished。"""
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL)
            stats = store.sweep_expired_battles()
            if stats["finished"]:
                log.info(f"[sweep] finished={stats['finished']} (waiting={stats['by_waiting']}, ongoing={stats['by_ongoing']}) checked={stats['checked']}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception(f"[sweep] error: {e}")
            # 失败也继续，下个周期再试
            await asyncio.sleep(30)


@app.on_event("startup")
async def _start_sweeper():
    app.state.sweeper = asyncio.create_task(_sweeper_loop())
    log.info(f"[sweeper] started, interval={SWEEP_INTERVAL}s")


@app.on_event("shutdown")
async def _stop_sweeper():
    task = app.state.sweeper
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# 手动触发清理（便于测试 / 紧急清理）
@app.post("/api/admin/sweep")
def admin_sweep():
    return store.sweep_expired_battles()


@app.get("/api/admin/sweeper")
def admin_sweeper_status():
    """返回后台 sweeper task 状态。"""
    t = getattr(app.state, "sweeper", None)
    if t is None:
        return {"exists": False}
    return {
        "exists": True,
        "done": t.done(),
        "cancelled": t.cancelled(),
        "interval": SWEEP_INTERVAL,
    }


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


# ---------- 对战房间列表 ----------
@app.get("/api/battles")
def list_battles(req: Request):
    """列出所有未结束的对战房间。"""
    user = me(req)
    return {
        "user": user,
        "battles": store.list_active_battles(user["id"]),
    }


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
    ip = client_ip(req)
    # 限流：单个 IP 8 小时内最多 3 场对战
    if not store.check_create_limit(ip):
        raise HTTPException(429, "8 小时内创建对战次数已达上限（3 场），请稍后再试")
    battle = store.create_battle(user["id"], body.type, body.max_players, body.total_matches,
                                 body.best_of, body.game_point)
    store.record_create(ip, battle["id"])
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
    _with_team_players(match)
    return match


def _with_team_players(match: dict) -> dict:
    """为 match 的 team_a / team_b 补充玩家信息（昵称、头像）。"""
    bid = match.get("battle_id")
    if bid:
        players = store.get_players(bid)
        pmap = {p["id"]: p for p in players}
        match["team_a_players"] = [pmap.get(u, {"id": u, "nickname": u, "avatar": "?"}) for u in match.get("team_a", [])]
        match["team_b_players"] = [pmap.get(u, {"id": u, "nickname": u, "avatar": "?"}) for u in match.get("team_b", [])]
    else:
        match["team_a_players"] = []
        match["team_b_players"] = []
    return match


@app.get("/api/match/{mid}")
def get_match(mid: str):
    match = store.get_match(mid)
    if not match:
        raise HTTPException(404, "对战不存在")
    match["court"] = court_info(match)
    _with_team_players(match)
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
# 前端文件在项目根目录（与 GitHub Pages 部署结构一致）
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT_DIR, "index.html"))


# 静态资源（css/js 用相对路径引用，挂载 /css 和 /js）
app.mount("/css", StaticFiles(directory=os.path.join(ROOT_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(ROOT_DIR, "js")), name="js")


@app.get("/battle.html")
def battle_page():
    return FileResponse(os.path.join(ROOT_DIR, "battle.html"))


@app.get("/matches.html")
def matches_page():
    return FileResponse(os.path.join(ROOT_DIR, "matches.html"))


@app.get("/watch.html")
def watch_page():
    return FileResponse(os.path.join(ROOT_DIR, "watch.html"))


# PWA 图标与清单文件
@app.get("/manifest.json")
def manifest():
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"), media_type="application/json")


_STATIC_ICONS = {
    "favicon.png": "image/png",
    "apple-touch-icon.png": "image/png",
    "apple-touch-icon-watch.png": "image/png",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}


@app.get("/{filename}")
def static_icon(filename: str):
    if filename in _STATIC_ICONS:
        path = os.path.join(ROOT_DIR, filename)
        if os.path.exists(path):
            return FileResponse(path, media_type=_STATIC_ICONS[filename])
    raise HTTPException(404, "Not Found")


if __name__ == "__main__":
    import argparse
    import platform
    import signal
    import subprocess
    import sys
    import time
    import uvicorn

    IS_WINDOWS = sys.platform == "win32"
    IS_MACOS = sys.platform == "darwin"
    IS_BSD = sys.platform.startswith("freebsd") or IS_MACOS
    IS_POSIX = not IS_WINDOWS

    parser = argparse.ArgumentParser(description="LetsPlay 对战记分后端")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    parser.add_argument("--daemon", "-d", action="store_true", help="以守护进程方式后台运行")
    parser.add_argument("--stop", action="store_true", help="停止后台运行的服务")
    parser.add_argument("--status", action="store_true", help="查看服务运行状态")
    parser.add_argument("--pidfile", default="letsplay.pid", help="PID 文件路径 (默认 letsplay.pid)")
    parser.add_argument("--logfile", default="letsplay.log", help="日志文件路径 (默认 letsplay.log)")
    args = parser.parse_args()

    def _pid_alive(pid: int) -> bool:
        """跨平台检测进程是否存活。"""
        if IS_WINDOWS:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            STILL_ACTIVE = 259
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        else:
            try:
                os.kill(pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                return False
            except OSError:
                return False

    def _terminate_process(pid: int, graceful: bool = True) -> bool:
        """跨平台终止进程。

        macOS / Linux: 先 SIGTERM 进程组（同时终止子进程），超时后 SIGKILL。
        Windows: taskkill /T 终止进程树。
        """
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/F" if not graceful else "/T", "/PID", str(pid)],
                    capture_output=True, check=False,
                )
                return True
            except FileNotFoundError:
                # 极端回退：直接发信号（需要 pywin32）
                return False
        else:
            try:
                if graceful:
                    # 优先终止整个进程组（macOS / Linux 均支持）
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        os.kill(pid, signal.SIGTERM)
                    # 等待最多 5 秒
                    for _ in range(50):
                        time.sleep(0.1)
                        if not _pid_alive(pid):
                            return True
                    # 兜底：SIGKILL
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        os.kill(pid, signal.SIGKILL)
                else:
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        os.kill(pid, signal.SIGKILL)
                return True
            except (ProcessLookupError, OSError):
                return False

    if args.daemon:
        pidfile = args.pidfile
        logfile = args.logfile

        # 检查是否已在运行
        if os.path.exists(pidfile):
            try:
                with open(pidfile, "r") as f:
                    old_pid = int(f.read().strip())
                if _pid_alive(old_pid):
                    print(f"服务已在运行 (PID {old_pid})，如需重启请先停止")
                    sys.exit(1)
            except (ValueError, OSError):
                pass
            # 旧 PID 文件已失效，清理
            try:
                os.remove(pidfile)
            except FileNotFoundError:
                pass

        # 以后台方式启动新进程
        log_f = open(logfile, "a", encoding="utf-8")

        # 构造启动命令（不带 --daemon，避免无限递归）
        cmd = [sys.executable, os.path.abspath(__file__),
               "--host", args.host, "--port", str(args.port)]

        popen_kwargs = {
            "stdout": log_f,
            "stderr": log_f,
            "stdin": subprocess.DEVNULL,
        }

        if IS_WINDOWS:
            # 脱离父进程，独立进程组
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            popen_kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            # macOS / Linux: 启动新会话
            popen_kwargs["start_new_session"] = True

        # macOS 在某些 Python 版本上 close_fds 会引发 OSError，使用 try/except 兜底
        try:
            popen_kwargs["close_fds"] = True
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except (OSError, ValueError):
            popen_kwargs.pop("close_fds", None)
            proc = subprocess.Popen(cmd, **popen_kwargs)

        log_f.close()

        # 写入 PID 文件
        with open(pidfile, "w") as f:
            f.write(str(proc.pid))

        # 等待服务启动
        time.sleep(1.5)

        # 检查进程是否仍在运行
        if _pid_alive(proc.pid):
            print(f"服务已后台启动 (PID {proc.pid}) [{platform.system()} {platform.release()}]")
            print(f"日志: {os.path.abspath(logfile)}")
            print(f"PID 文件: {os.path.abspath(pidfile)}")
            print(f"停止: python main.py --stop")
        else:
            print("服务启动失败，请检查日志:")
            print(f"  {os.path.abspath(logfile)}")
            try:
                os.remove(pidfile)
            except FileNotFoundError:
                pass
            sys.exit(1)
    elif args.stop:
        pidfile = args.pidfile

        if not os.path.exists(pidfile):
            print("服务未运行（PID 文件不存在）")
            sys.exit(0)

        try:
            with open(pidfile, "r") as f:
                pid = int(f.read().strip())
        except (ValueError, OSError) as e:
            print(f"PID 文件无效: {e}")
            try:
                os.remove(pidfile)
            except FileNotFoundError:
                pass
            sys.exit(1)

        if _terminate_process(pid, graceful=True):
            print(f"服务已停止 (PID {pid})")
        else:
            print(f"进程 {pid} 不存在或无法终止，清理 PID 文件")

        try:
            os.remove(pidfile)
        except FileNotFoundError:
            pass
    elif args.status:
        pidfile = args.pidfile

        if not os.path.exists(pidfile):
            print("服务未运行")
            sys.exit(0)

        try:
            with open(pidfile, "r") as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            print("PID 文件无效")
            sys.exit(1)

        if _pid_alive(pid):
            print(f"服务运行中 (PID {pid}) [{platform.system()}]")
            sys.exit(0)
        else:
            print("服务未运行（PID 文件存在但进程已退出）")
            try:
                os.remove(pidfile)
            except FileNotFoundError:
                pass
            sys.exit(1)
    else:
        uvicorn.run(app, host=args.host, port=args.port)
