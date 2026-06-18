"""根据用户 IP 确定性生成昵称与头像（SVG）。同一 IP 永远得到同一身份。"""
import hashlib

# 形容词池：运动/竞技感
ADJECTIVES = [
    "冲刺的","跳跃的","翻滚的","旋转的","弹动的","摇摆的",
    "滑行的","蹬踏的","摆动的","抖动的","抛接的","闪避的",
    "加速的","腾空的","扭转的","漂移的","反弹的","跨步的",
    "俯冲的","起跑的"
]

# 动物池：以鸟类为主（呼应羽毛球）
ANIMALS = [
    "隼", "鹰", "鸭", "鸟", "雀", "雕", "鹅",
    "猫","狗","兔","熊","鹿","狐狸","鲸","企鹅","松鼠","刺猬","熊猫",
    "考拉","水獭","仓鼠"
]


def _hash_ip(ip: str) -> int:
    """将 IP 哈希为稳定整数。"""
    h = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    return int(h, 16)


def generate_identity(ip: str) -> dict:
    """根据 IP 生成 {id, nickname, avatar_svg}。"""
    seed = _hash_ip(ip)
    adj = ADJECTIVES[seed % len(ADJECTIVES)]
    animal = ANIMALS[(seed >> 8) % len(ANIMALS)]
    number = (seed >> 16) % 900 + 100
    nickname = f"{adj}{animal}{number}"

    avatar = _build_avatar(seed)
    return {
        "id": f"u{seed % 0xFFFFFFFF:08x}",
        "nickname": nickname,
        "avatar": avatar,
    }


def _build_avatar(seed: int) -> str:
    """生成确定性几何头像 SVG（5x5 对称色块，类似 identicon）。"""
    palette = [
        ["#d4ff3a", "#0a0e1a"],  # lime / night
        ["#ff5e3a", "#0a0e1a"],  # coral / night
        ["#3ad4ff", "#0a0e1a"],  # cyan / night
        ["#ffd23a", "#0a0e1a"],  # gold / night
        ["#ff3a8c", "#0a0e1a"],  # magenta / night
        ["#3aff9e", "#0a0e1a"],  # mint / night
        ["#a23aff", "#0a0e1a"],  # violet / night
        ["#3affd2", "#0a0e1a"],  # aqua / night
    ]
    pair = palette[(seed >> 24) % len(palette)]
    fg, bg = pair[0], pair[1]

    # 5x5 对称矩阵：左 3 列决定整行
    cells = []
    bit = seed >> 32
    for row in range(5):
        for col in range(3):  # 只取左 3 列
            on = (bit >> (row * 3 + col)) & 1
            if on:
                cells.append((col, row))
                if col < 2:  # 镜像到右侧
                    cells.append((4 - col, row))
                else:
                    if (col, row) not in cells:
                        cells.append((4 - col, row))

    rects = ""
    for (cx, cy) in dict.fromkeys(cells):  # 去重保序
        rects += f'<rect x="{cx*8}" y="{cy*8}" width="8" height="8" fill="{fg}"/>'

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
        f'shape-rendering="crispEdges">'
        f'<rect width="40" height="40" fill="{bg}"/>'
        f"{rects}"
        f"</svg>"
    )
    return svg
