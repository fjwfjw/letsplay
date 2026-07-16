"""Redis 存储层：所有数据持久化操作集中在此。"""
import json
import time
import uuid
import redis

from nickname import generate_identity
from matchmaker import generate_matches, fairness_report, generate_free_matches

# TTL（秒）：对战活跃时保留 24h；结束后保留 2h 再清理；用户身份 90 天
BATTLE_TTL = 24 * 3600
FINISHED_TTL = 2 * 3600
USER_TTL = 90 * 24 * 3600
TOKEN_TTL = 90 * 24 * 3600
FRIEND_TTL = 90 * 24 * 3600
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
                "gender": "unknown",
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
            "gender": data.get("gender", "unknown"),
            "ip": data.get("ip", ""),
        }

    def update_profile(self, uid: str, nickname: str = None, gender: str = None, avatar: str = None) -> dict:
        """更新用户昵称、性别和/或头像。"""
        key = f"user:{uid}"
        if not self.r.exists(key):
            return None
        mapping = {}
        if nickname is not None:
            mapping["nickname"] = nickname
        if gender is not None:
            mapping["gender"] = gender
        if avatar is not None:
            mapping["avatar"] = avatar
        if mapping:
            self.r.hset(key, mapping=mapping)
        self.r.expire(key, USER_TTL)
        return self.get_user(uid)

    # ---------- 注册 / 登录 / Token ----------
    def register_user(self, login_key: str, gender: str, ip: str, nickname: str = None, avatar: str = None) -> dict:
        """首次注册：密钥查重，用 IP 生成昵称头像（可覆盖），返回 user + token。"""
        # 密钥查重
        existing_uid = self.r.get(f"key:{login_key}")
        if existing_uid:
            raise ValueError("该密钥已被注册")
        # 用 IP 生成确定性身份
        ident = generate_identity(ip)
        uid = ident["id"]
        # 允许自定义昵称和头像，否则用 IP 派生的
        final_nick = nickname if nickname else ident["nickname"]
        final_avatar = avatar if avatar else ident["avatar"]
        key = f"user:{uid}"
        if not self.r.exists(key):
            self.r.hset(key, mapping={
                "id": uid,
                "nickname": final_nick,
                "avatar": final_avatar,
                "gender": gender,
                "ip": ip,
                "login_key": login_key,
                "created_at": int(time.time()),
            })
        else:
            # 用户已存在（IP 派生），覆盖昵称头像和 login_key
            mapping = {"login_key": login_key, "gender": gender, "nickname": final_nick, "avatar": final_avatar}
            self.r.hset(key, mapping=mapping)
        self.r.expire(key, USER_TTL)
        # 存密钥 -> uid 映射
        self.r.set(f"key:{login_key}", uid, ex=USER_TTL)
        # 生成 token
        token = uuid.uuid4().hex
        self.r.set(f"token:{token}", uid, ex=TOKEN_TTL)
        user = self.get_user(uid)
        user["token"] = token
        return user

    def login_user(self, login_key: str) -> dict:
        """密钥登录：返回 user + token。"""
        uid = self.r.get(f"key:{login_key}")
        if not uid:
            raise ValueError("密钥不存在，请先注册")
        user = self.get_user(uid)
        if not user:
            raise ValueError("用户数据不存在")
        # 生成新 token
        token = uuid.uuid4().hex
        self.r.set(f"token:{token}", uid, ex=TOKEN_TTL)
        user["token"] = token
        return user

    def get_user_by_token(self, token: str) -> dict:
        """通过 token 获取用户。"""
        uid = self.r.get(f"token:{token}")
        if not uid:
            return None
        return self.get_user(uid)

    # ---------- 好友 ----------
    def send_friend_request(self, from_uid: str, to_uid: str) -> dict:
        """发送好友请求。"""
        if from_uid == to_uid:
            raise ValueError("不能加自己为好友")
        if not self.r.exists(f"user:{to_uid}"):
            raise ValueError("目标用户不存在")
        # 已是好友
        if self.r.sismember(f"friends:{from_uid}", to_uid):
            raise ValueError("已经是好友了")
        # 互相请求 -> 直接成为好友
        if self.r.sismember(f"friend_req:{from_uid}", to_uid):
            # 对方已请求加我，直接互加
            self.r.sadd(f"friends:{from_uid}", to_uid)
            self.r.sadd(f"friends:{to_uid}", from_uid)
            self.r.srem(f"friend_req:{from_uid}", to_uid)
            self.r.expire(f"friends:{from_uid}", FRIEND_TTL)
            self.r.expire(f"friends:{to_uid}", FRIEND_TTL)
            return {"ok": True, "accepted": True}
        # 发送请求
        self.r.sadd(f"friend_req:{to_uid}", from_uid)
        self.r.expire(f"friend_req:{to_uid}", FRIEND_TTL)
        return {"ok": True, "accepted": False}

    def accept_friend_request(self, from_uid: str, to_uid: str) -> dict:
        """接受好友请求。"""
        if not self.r.sismember(f"friend_req:{to_uid}", from_uid):
            raise ValueError("没有来自该用户的好友请求")
        self.r.sadd(f"friends:{to_uid}", from_uid)
        self.r.sadd(f"friends:{from_uid}", to_uid)
        self.r.srem(f"friend_req:{to_uid}", from_uid)
        self.r.expire(f"friends:{to_uid}", FRIEND_TTL)
        self.r.expire(f"friends:{from_uid}", FRIEND_TTL)
        return {"ok": True}

    def get_friends(self, uid: str) -> list:
        """获取好友列表。"""
        uids = self.r.smembers(f"friends:{uid}")
        friends = []
        for fuid in uids:
            u = self.get_user(fuid)
            if u:
                friends.append(u)
        return friends

    def get_friend_requests(self, uid: str) -> list:
        """获取待处理的好友请求列表。"""
        uids = self.r.smembers(f"friend_req:{uid}")
        reqs = []
        for fuid in uids:
            u = self.get_user(fuid)
            if u:
                reqs.append(u)
        return reqs

    def is_friend(self, uid: str, other_uid: str) -> bool:
        return self.r.sismember(f"friends:{uid}", other_uid)

    # ---------- 个人统计 ----------
    def get_user_stats(self, uid: str) -> dict:
        """获取用户对战统计：对战记录、胜率、组队胜率。"""
        user = self.get_user(uid)
        if not user:
            raise ValueError("用户不存在")

        matches_played = 0
        matches_won = 0
        games_played = 0
        games_won = 0
        history = []
        teammate_stats = {}  # uid -> {played, won}

        # 扫描所有对战
        for key in self.r.scan_iter(match="battle:*", count=200):
            key = key.decode() if isinstance(key, bytes) else key
            if key.endswith(":players") or key.endswith(":matches"):
                continue
            bid = key.split(":", 1)[1]
            battle = self.get_battle(bid)
            if not battle:
                continue
            players = self.get_players(bid)
            player_ids = [p["id"] for p in players]
            if uid not in player_ids:
                continue
            matches = self.get_matches(bid) if battle["status"] in ("ongoing", "finished") else []
            user_matches = []
            for m in matches:
                team_a = m.get("team_a", [])
                team_b = m.get("team_b", [])
                if uid not in team_a and uid not in team_b:
                    continue
                user_team = team_a if uid in team_a else team_b
                opp_team = team_b if uid in team_a else team_a
                user_game = m["game_a"] if uid in team_a else m["game_b"]
                opp_game = m["game_b"] if uid in team_a else m["game_a"]
                is_win = m["status"] == "done" and user_game > opp_game
                if m["status"] == "done":
                    matches_played += 1
                    if is_win:
                        matches_won += 1
                games_played += user_game + opp_game
                games_won += user_game
                # 队友统计
                teammates = [t for t in user_team if t != uid]
                for t in teammates:
                    if t not in teammate_stats:
                        teammate_stats[t] = {"played": 0, "won": 0, "nickname": "", "avatar": ""}
                    teammate_stats[t]["played"] += 1
                    if is_win:
                        teammate_stats[t]["won"] += 1
                user_matches.append({
                    "index": m["index"],
                    "status": m["status"],
                    "score_a": m["score_a"],
                    "score_b": m["score_b"],
                    "game_a": m["game_a"],
                    "game_b": m["game_b"],
                    "win": is_win,
                    "team": "a" if uid in team_a else "b",
                })
            if user_matches:
                creator = next((p for p in players if p["id"] == battle["creator_id"]), None)
                history.append({
                    "battle_id": bid,
                    "type": battle["type"],
                    "status": battle["status"],
                    "created_at": int(battle["created_at"]),
                    "finished_at": int(battle["finished_at"]) if battle.get("finished_at") else None,
                    "total_matches": battle["total_matches"],
                    "best_of": battle["best_of"],
                    "game_point": battle["game_point"],
                    "my_matches": user_matches,
                    "creator": creator,
                    "players_count": len(players),
                })

        # 填充队友信息
        for tuid, stats in teammate_stats.items():
            tu = self.get_user(tuid)
            if tu:
                stats["nickname"] = tu["nickname"]
                stats["avatar"] = tu["avatar"]
                stats["id"] = tuid

        history.sort(key=lambda x: x["created_at"], reverse=True)
        win_rate = round(matches_won / matches_played * 100, 1) if matches_played > 0 else 0
        teammate_list = sorted(teammate_stats.values(), key=lambda x: x["played"], reverse=True)

        return {
            "user": user,
            "matches_played": matches_played,
            "matches_won": matches_won,
            "win_rate": win_rate,
            "games_played": games_played,
            "games_won": games_won,
            "history": history,
            "teammates": teammate_list,
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
                      best_of: int = 3, game_point: int = 21, assign_mode: str = "random",
                      gender_rule: str = "none") -> dict:
        bid = uuid.uuid4().hex[:8]
        now = int(time.time())
        self.r.hset(f"battle:{bid}", mapping={
            "id": bid,
            "type": match_type,
            "max_players": str(max_players),
            "total_matches": str(total_matches),
            "best_of": str(best_of),
            "game_point": str(game_point),
            "assign_mode": assign_mode,  # random | free
            "gender_rule": gender_rule,  # none | mixed | separated
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
        data["assign_mode"] = data.get("assign_mode", "random")  # 兼容旧数据
        data["gender_rule"] = data.get("gender_rule", "none")  # 兼容旧数据
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

    # ---------- 分配模式与自由组队 ----------
    def set_assign_mode(self, bid: str, mode: str) -> dict:
        """设置对战分配模式（仅 waiting 状态可改）。"""
        battle = self.get_battle(bid)
        if not battle:
            raise ValueError("对战不存在")
        if battle["status"] != "waiting":
            raise ValueError("对战已开始，无法修改分配模式")
        if mode not in ("random", "free"):
            raise ValueError("模式必须为 random 或 free")
        self.r.hset(f"battle:{bid}", "assign_mode", mode)
        return self.get_battle(bid)

    def set_gender_rule(self, bid: str, rule: str) -> dict:
        """设置对战性别规则（仅 waiting 状态可改）。"""
        battle = self.get_battle(bid)
        if not battle:
            raise ValueError("对战不存在")
        if battle["status"] != "waiting":
            raise ValueError("对战已开始，无法修改性别规则")
        if rule not in ("none", "mixed", "separated"):
            raise ValueError("性别规则必须为 none | mixed | separated")
        self.r.hset(f"battle:{bid}", "gender_rule", rule)
        return self.get_battle(bid)

    def set_teams(self, bid: str, teams: dict) -> dict:
        """保存自由组队配置。teams = {"team_0": [uid,...], ...}"""
        battle = self.get_battle(bid)
        if not battle:
            raise ValueError("对战不存在")
        if battle["status"] != "waiting":
            raise ValueError("对战已开始，无法修改队伍")
        # 校验：所有 uid 必须是已加入玩家，且不重复
        joined = set(self.r.smembers(f"battle:{bid}:players"))
        seen = set()
        for tid, uids in teams.items():
            for u in uids:
                if u not in joined:
                    raise ValueError(f"玩家 {u} 未加入对战")
                if u in seen:
                    raise ValueError(f"玩家 {u} 被重复分配")
                seen.add(u)
        self.r.set(f"battle:{bid}:teams", json.dumps(teams))
        self.r.expire(f"battle:{bid}:teams", BATTLE_TTL)
        return self.get_teams(bid)

    def get_teams(self, bid: str) -> dict:
        raw = self.r.get(f"battle:{bid}:teams")
        if not raw:
            return {}
        return json.loads(raw)

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
        assign_mode = battle.get("assign_mode", "random")

        if assign_mode == "free":
            teams = self.get_teams(bid)
            if len(teams) < 2:
                raise ValueError("自由对战至少需要 2 支队伍")
            # 校验每队人数符合单/双打要求
            per_team = 1 if battle["type"] == "singles" else 2
            for tid, uids in teams.items():
                if len(uids) != per_team:
                    raise ValueError(f"每支队伍需 {per_team} 人")
            matches = generate_free_matches(teams, battle["total_matches"], seed)
        else:
            gender_rule = battle.get("gender_rule", "none")
            # 构建性别映射
            gender_map = {}
            if gender_rule != "none":
                for uid in players_uids:
                    user = self.get_user(uid)
                    gender_map[uid] = user.get("gender", "unknown") if user else "unknown"
            result = generate_matches(players_uids, battle["type"], battle["total_matches"], seed,
                                      gender_rule=gender_rule, gender_map=gender_map)
            matches = result["matches"]
            self._gender_fallback = result.get("fallback", False)

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
        return {"matches": self.get_matches(bid), "gender_fallback": getattr(self, "_gender_fallback", False)}

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
        pipe.expire(f"battle:{bid}:teams", ttl)
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
        """扫描所有未结束的对战，返回当前用户创建的、已加入的、或好友的房间。

        返回按创建时间倒序排列的列表，每项含 battle 基础字段、玩家数、玩家列表、
        以及当前用户是否已加入该对战 (joined)、是否好友房间 (is_friend)。
        """
        # 获取好友列表
        friend_ids = set()
        if uid:
            friend_ids = self.r.smembers(f"friends:{uid}")
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
            is_friend_room = bool(friend_ids & set(player_ids))
            # 显示：自己创建的、已加入的、好友的房间
            if not is_creator and not is_joined and not is_friend_room:
                continue
            out.append({
                "id": bid,
                "type": battle["type"],
                "max_players": battle["max_players"],
                "total_matches": battle["total_matches"],
                "best_of": battle["best_of"],
                "game_point": battle["game_point"],
                "assign_mode": battle.get("assign_mode", "random"),
                "gender_rule": battle.get("gender_rule", "none"),
                "status": battle["status"],
                "creator_id": battle["creator_id"],
                "created_at": int(battle["created_at"]),
                "players_count": len(players),
                "players": players,
                "joined": is_joined,
                "is_friend": is_friend_room and not is_creator and not is_joined,
                "is_full": len(players) >= battle["max_players"],
            })
        out.sort(key=lambda x: x["created_at"], reverse=True)
        return out

    def list_all_battles(self) -> list:
        """扫描所有对战（含已结束），返回完整信息含人员和每场比分。用于后台管理页。"""
        out = []
        for key in self.r.scan_iter(match="battle:*", count=200):
            key = key.decode() if isinstance(key, bytes) else key
            if key.endswith(":players") or key.endswith(":matches"):
                continue
            bid = key.split(":", 1)[1]
            battle = self.get_battle(bid)
            if not battle:
                continue
            players = self.get_players(bid)
            matches = self.get_matches(bid) if battle["status"] in ("ongoing", "finished") else []
            # 为每场补充队伍球员信息
            pmap = {p["id"]: p for p in players}
            for m in matches:
                m["team_a_players"] = [pmap.get(u, {"id": u, "nickname": u, "avatar": "?"}) for u in m.get("team_a", [])]
                m["team_b_players"] = [pmap.get(u, {"id": u, "nickname": u, "avatar": "?"}) for u in m.get("team_b", [])]
            creator = pmap.get(battle["creator_id"], {"id": battle["creator_id"], "nickname": battle["creator_id"], "avatar": "?"})
            out.append({
                "id": bid,
                "type": battle["type"],
                "max_players": battle["max_players"],
                "total_matches": battle["total_matches"],
                "best_of": battle["best_of"],
                "game_point": battle["game_point"],
                "assign_mode": battle.get("assign_mode", "random"),
                "gender_rule": battle.get("gender_rule", "none"),
                "status": battle["status"],
                "creator": creator,
                "created_at": int(battle["created_at"]),
                "finished_at": int(battle["finished_at"]) if battle.get("finished_at") else None,
                "players_count": len(players),
                "players": players,
                "matches": matches,
            })
        out.sort(key=lambda x: x["created_at"], reverse=True)
        return out

