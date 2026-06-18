"""Redis 存储层：所有数据持久化操作集中在此。"""
import json
import time
import uuid
import redis

from nickname import generate_identity
from matchmaker import generate_matches, fairness_report

# TTL（秒）：对战活跃时保留 24h；结束后保留 2h 再清理；用户身份 7 天
BATTLE_TTL = 24 * 3600
FINISHED_TTL = 2 * 3600
USER_TTL = 7 * 24 * 3600
# 过期清理阈值：waiting 超过 N 秒 / ongoing 超过 M 秒自动 finished
WAITING_EXPIRE = 4 * 3600
ONGOING_EXPIRE = 8 * 3600
# 建赛限流：单个 IP 在窗口期内最多创建 N 场对战
CREATE_LIMIT_WINDOW = 8 * 3600   # 8 小时
CREATE_LIMIT_MAX = 3             # 最多 3 场


def get_redis(host="localhost", port=6379, db=0):
    return redis.Redis(host=host, port=port, db=db, decode_responses=True)


class Store:
    def __init__(self, r: redis.Redis):
        self.r = r

    # ---------- 用户 ----------
    def get_or_create_user(self, ip: str) -> dict:
        """根据 IP 取/建用户，同一 IP 永远同一身份。"""
        ident = generate_identity(ip)
        uid = ident["id"]
        key = f"user:{uid}"
        if not self.r.exists(key):
            self.r.hset(key, mapping={
                "id": uid,
                "nickname": ident["nickname"],
                "avatar": ident["avatar"],
                "ip": ip,
                "created_at": int(time.time()),
            })
        self.r.expire(key, USER_TTL)  # 访问即续期
        return self.get_user(uid)

    def get_user(self, uid: str) -> dict:
        key = f"user:{uid}"
        data = self.r.hgetall(key)
        if not data:
            return None
        self.r.expire(key, USER_TTL)  # 续期
        return {
            "id": data["id"],
            "nickname": data["nickname"],
            "avatar": data["avatar"],
            "ip": data.get("ip", ""),
        }

    # ---------- 对战 ----------
    def check_create_limit(self, ip: str) -> bool:
        """检查单个 IP 在 8h 窗口内是否可继续建赛（只读，不修改计数）。"""
        key = f"ratelimit:create:{ip}"
        now = int(time.time())
        # 移除窗口外的过期记录
        self.r.zremrangebyscore(key, 0, now - CREATE_LIMIT_WINDOW)
        count = self.r.zcard(key)
        return count < CREATE_LIMIT_MAX

    def record_create(self, ip: str, bid: str):
        """建赛成功后记录一条（用于限流计数）。"""
        key = f"ratelimit:create:{ip}"
        now = int(time.time())
        self.r.zadd(key, {bid: now})
        self.r.expire(key, CREATE_LIMIT_WINDOW)

    def create_battle(self, creator_uid: str, match_type: str, max_players: int, total_matches: int,
                      best_of: int = 3, game_point: int = 21) -> dict:
        bid = uuid.uuid4().hex[:8]
        now = int(time.time())
        self.r.hset(f"battle:{bid}", mapping={
            "id": bid,
            "type": match_type,
            "max_players": str(max_players),
            "total_matches": str(total_matches),
            "best_of": str(best_of),
            "game_point": str(game_point),
            "status": "waiting",  # waiting | ongoing | finished
            "creator_id": creator_uid,
            "created_at": str(now),
        })
        # 创建者自动加入
        self.r.sadd(f"battle:{bid}:players", creator_uid)
        self._refresh_battle_ttl(bid, BATTLE_TTL)
        return self.get_battle(bid)

    def get_battle(self, bid: str) -> dict:
        data = self.r.hgetall(f"battle:{bid}")
        if not data:
            return None
        data["max_players"] = int(data["max_players"])
        data["total_matches"] = int(data["total_matches"])
        data["best_of"] = int(data.get("best_of", "3"))
        data["game_point"] = int(data.get("game_point", "21"))
        # 活跃对战访问即续期；已结束的保持短 TTL 不续
        if data["status"] != "finished":
            self._refresh_battle_ttl(bid, BATTLE_TTL)
        return data

    def get_players(self, bid: str) -> list:
        uids = self.r.smembers(f"battle:{bid}:players")
        return [self.get_user(u) for u in uids if self.get_user(u)]

    def join_battle(self, bid: str, uid: str) -> dict:
        battle = self.get_battle(bid)
        if not battle:
            raise ValueError("对战不存在")
        if battle["status"] != "waiting":
            raise ValueError("对战已开始，无法加入")
        count = self.r.scard(f"battle:{bid}:players")
        if uid not in self.r.smembers(f"battle:{bid}:players") and count >= battle["max_players"]:
            raise ValueError("人数已满")
        self.r.sadd(f"battle:{bid}:players", uid)
        return {"ok": True}

    def is_player(self, bid: str, uid: str) -> bool:
        return uid in self.r.smembers(f"battle:{bid}:players")

    def start_battle(self, bid: str, uid: str) -> dict:
        battle = self.get_battle(bid)
        if not battle:
            raise ValueError("对战不存在")
        if battle["creator_id"] != uid:
            raise ValueError("仅创建者可开始")
        if battle["status"] != "waiting":
            raise ValueError("对战已开始")
        players_uids = list(self.r.smembers(f"battle:{bid}:players"))
        min_players = 2 if battle["type"] == "singles" else 4
        if len(players_uids) < min_players:
            raise ValueError(f"至少需要 {min_players} 人")

        seed = int(battle["created_at"]) + hash(bid)
        matches = generate_matches(players_uids, battle["type"], battle["total_matches"], seed)

        pipe = self.r.pipeline()
        pipe.hset(f"battle:{bid}", "status", "ongoing")
        pipe.delete(f"battle:{bid}:matches")
        for m in matches:
            mid = f"{bid}_{m['index']:03d}"
            pipe.hset(f"match:{mid}", mapping={
                "id": mid,
                "battle_id": bid,
                "index": str(m["index"]),
                "team_a": json.dumps(m["team_a"]),
                "team_b": json.dumps(m["team_b"]),
                "score_a": "0",
                "score_b": "0",
                "game_a": "0",
                "game_b": "0",
                "server": "a",
                "status": "pending",  # pending | live | done
                "history": "[]",
                "games_detail": "[]",
                "best_of": str(battle["best_of"]),
                "game_point": str(battle["game_point"]),
            })
            pipe.rpush(f"battle:{bid}:matches", mid)
            pipe.expire(f"match:{mid}", BATTLE_TTL)
        pipe.expire(f"battle:{bid}:matches", BATTLE_TTL)
        pipe.execute()
        self._refresh_battle_ttl(bid, BATTLE_TTL)
        return self.get_matches(bid)

    def get_matches(self, bid: str) -> list:
        mids = self.r.lrange(f"battle:{bid}:matches", 0, -1)
        out = []
        for mid in mids:
            out.append(self.get_match(mid))
        return out

    def get_match(self, mid: str) -> dict:
        data = self.r.hgetall(f"match:{mid}")
        if not data:
            return None
        data["team_a"] = json.loads(data["team_a"])
        data["team_b"] = json.loads(data["team_b"])
        data["index"] = int(data["index"])
        data["score_a"] = int(data["score_a"])
        data["score_b"] = int(data["score_b"])
        data["game_a"] = int(data["game_a"])
        data["game_b"] = int(data["game_b"])
        data["history"] = json.loads(data["history"])
        data["games_detail"] = json.loads(data.get("games_detail", "[]"))
        data["best_of"] = int(data.get("best_of", "3"))
        data["game_point"] = int(data.get("game_point", "21"))
        return data

    def get_fairness(self, bid: str) -> dict:
        battle = self.get_battle(bid)
        if not battle:
            return {}
        players_uids = list(self.r.smembers(f"battle:{bid}:players"))
        matches = self.get_matches(bid)
        return fairness_report(players_uids, matches, battle["type"])

    # ---------- TTL 管理 ----------
    def _refresh_battle_ttl(self, bid: str, ttl: int):
        """刷新一场对战相关所有 key 的过期时间。"""
        pipe = self.r.pipeline()
        pipe.expire(f"battle:{bid}", ttl)
        pipe.expire(f"battle:{bid}:players", ttl)
        pipe.expire(f"battle:{bid}:matches", ttl)
        for mid in self.r.lrange(f"battle:{bid}:matches", 0, -1):
            pipe.expire(f"match:{mid}", ttl)
        pipe.execute()

    def check_finish_battle(self, bid: str) -> bool:
        """全部比赛结束则标记对战 finished，并缩短 TTL 至 FINISHED_TTL，到期自动清理。"""
        battle = self.get_battle(bid)
        if not battle or battle["status"] == "finished":
            return battle is not None and battle["status"] == "finished"
        matches = self.get_matches(bid)
        if not matches:
            return False
        if all(m["status"] == "done" for m in matches):
            self.r.hset(f"battle:{bid}", "status", "finished")
            self.r.hset(f"battle:{bid}", "finished_at", str(int(time.time())))
            # 缩短 TTL，到期后 Redis 自动清理
            self._refresh_battle_ttl(bid, FINISHED_TTL)
            return True
        return False

    def sweep_expired_battles(self) -> dict:
        """扫描所有 battle，waiting>4h 或 ongoing>8h 自动 finished。

        复用 check_finish_battle 的 TTL 缩短逻辑，让过期房 2h 后被 Redis 清理。
        返回本次扫描的统计：checked / finished / by_waiting / by_ongoing。
        """
        now = int(time.time())
        stats = {"checked": 0, "finished": 0, "by_waiting": 0, "by_ongoing": 0}
        for key in self.r.scan_iter(match="battle:*", count=200):
            key = key.decode() if isinstance(key, bytes) else key
            # 仅取 battle hash 本身
            if key.endswith(":players") or key.endswith(":matches"):
                continue
            bid = key.split(":", 1)[1]
            battle = self.get_battle(bid)
            if not battle or battle["status"] == "finished":
                continue
            stats["checked"] += 1
            created_at = int(battle.get("created_at", now))
            status = battle["status"]
            should_finish = False
            reason = None
            if status == "waiting" and now - created_at >= WAITING_EXPIRE:
                should_finish = True
                reason = "by_waiting"
            elif status == "ongoing" and now - created_at >= ONGOING_EXPIRE:
                should_finish = True
                reason = "by_ongoing"
            if should_finish:
                self.r.hset(f"battle:{bid}", "status", "finished")
                self.r.hset(f"battle:{bid}", "finished_at", str(now))
                self.r.hset(f"battle:{bid}", "finished_reason", reason)
                self._refresh_battle_ttl(bid, FINISHED_TTL)
                stats["finished"] += 1
                stats[reason] += 1
        return stats

    def list_active_battles(self, uid: str = None) -> list:
        """扫描所有未结束的对战，只返回当前用户创建的或已加入的房间。

        返回按创建时间倒序排列的列表，每项含 battle 基础字段、玩家数、玩家列表、
        以及当前用户是否已加入该对战 (joined)。
        """
        out = []
        for key in self.r.scan_iter(match="battle:*", count=200):
            key = key.decode() if isinstance(key, bytes) else key
            if key.endswith(":players") or key.endswith(":matches"):
                continue
            bid = key.split(":", 1)[1]
            battle = self.get_battle(bid)
            if not battle or battle["status"] == "finished":
                continue
            players = self.get_players(bid)
            player_ids = [p["id"] for p in players]
            is_creator = uid == battle["creator_id"]
            is_joined = uid in player_ids if uid else False
            # 只显示自己创建的或已加入的对战
            if not is_creator and not is_joined:
                continue
            out.append({
                "id": bid,
                "type": battle["type"],
                "max_players": battle["max_players"],
                "total_matches": battle["total_matches"],
                "best_of": battle["best_of"],
                "game_point": battle["game_point"],
                "status": battle["status"],
                "creator_id": battle["creator_id"],
                "created_at": int(battle["created_at"]),
                "players_count": len(players),
                "players": players,
                "joined": is_joined,
            })
        out.sort(key=lambda x: x["created_at"], reverse=True)
        return out

