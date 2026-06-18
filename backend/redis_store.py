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

    def list_active_battles(self, uid: str = None) -> list:
        """扫描所有未结束的对战，可选判断 uid 是否为玩家。

        返回按创建时间倒序排列的列表，每项含 battle 基础字段、玩家数、玩家列表、
        以及当前用户是否已加入该对战 (joined)。
        """
        out = []
        for key in self.r.scan_iter(match="battle:*", count=200):
            key = key.decode() if isinstance(key, bytes) else key
            # 仅取 battle hash 本身，跳过 battle:*:players / battle:*:matches
            if key.endswith(":players") or key.endswith(":matches"):
                continue
            bid = key.split(":", 1)[1]
            battle = self.get_battle(bid)
            if not battle or battle["status"] == "finished":
                continue
            players = self.get_players(bid)
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
                "joined": uid in [p["id"] for p in players] if uid else False,
            })
        out.sort(key=lambda x: x["created_at"], reverse=True)
        return out

