from datetime import datetime
from urllib.parse import quote
from flask import Flask, render_template, request

app = Flask(__name__)

# 表示件数の上限（将来的にここを変更するだけで調整可能）
MAX_DISPLAY = 10

# 対象エリア名（将来の多地域展開時にここを変更 or リスト化する）
AREA_NAME = "池袋"

# ソートキー: 営業中 > 待ちレベル(green/yellow/red) > 徒歩分数
WAIT_LEVEL_ORDER = {"green": 0, "yellow": 1, "red": 2}

def sort_key(shop):
    is_closed = 0 if shop["is_open"] else 1
    wait_order = WAIT_LEVEL_ORDER.get(shop["wait_level"], 9)
    return (is_closed, wait_order, shop["walk_minutes"])


# ============================================================
# おすすめスコア計算
# ============================================================
# 「今行くならここ」選定用。待ち時間を最重要とし、
# 距離・更新の新しさ・報告傾向を補助的に加点減点する。
#
# 加点の目安:
#   wait_level green  : +100
#   wait_level yellow : +40
#   wait_level red    : -50
#   距離（徒歩）      : 最大 +15（walk_minutes が少ないほど有利）
#   更新の新しさ      : 最大 +10（20分以内の更新を優遇）
#   報告傾向          : 空いてた +10 / 混んでた or やや混み -10
# ============================================================

SCORE_BY_WAIT = {"green": 300, "yellow": 30, "red": -100}

def compute_recommend_score(shop):
    score = SCORE_BY_WAIT.get(shop["wait_level"], 0)

    # 距離：徒歩分数が少ないほど加点（最大 +15）
    score += max(0, 15 - shop["walk_minutes"])

    # 更新の新しさ：20分以内を加点（最大 +10）
    score += max(0, (20 - shop["updated_minutes_ago"]) * 0.5)

    # 報告傾向
    summary = shop.get("report_summary") or ""
    if "空いてた" in summary:
        score += 10
    elif "混んでた" in summary or "やや混み" in summary:
        score -= 10

    return score


# ============================================================
# 混雑スコア計算
# ============================================================
# スコアの考え方:
#   ≤ 0 → green（すぐ入れる）
#     1 → yellow（少し待つ）
#   ≥ 2 → red（待つかも）
#
# 入力項目:
#   base_crowd_score    : 店舗固有のベーススコア（0〜2）
#   popular_level       : 人気度（1=普通 / 2=人気 / 3=超人気）
#   fast_turnover       : 回転が早い店か（True/False）
#   lunch_peak_strong   : 昼ピークの影響が特に強い店か
#   dinner_peak_strong  : 夜ピークの影響が特に強い店か
# ============================================================

def compute_wait_level(shop, now=None):
    """
    現在時刻・曜日・店舗属性から混雑スコアを計算し、
    wait_level（green/yellow/red）と reason（根拠文）を返す。
    """
    if now is None:
        now = datetime.now()

    score = shop["base_crowd_score"]
    weekday = now.weekday()   # 0=月 〜 6=日
    t = now.hour + now.minute / 60  # 小数時刻（例: 12:30 → 12.5）
    is_weekend = weekday >= 5
    is_peak = False

    # ---- 時間帯ルール ----
    if not is_weekend:
        if 11.5 <= t < 13.5:
            score += 1
            is_peak = True
            if shop.get("lunch_peak_strong"):
                score += 1
        elif 18.0 <= t < 20.0:
            score += 1
            is_peak = True
            if shop.get("dinner_peak_strong"):
                score += 1
        elif 14.0 <= t < 17.0:
            score -= 1
    else:
        if 12.0 <= t < 14.0:
            score += 1
            is_peak = True
            if shop.get("lunch_peak_strong"):
                score += 1
        elif 18.0 <= t < 21.0:
            score += 1
            is_peak = True
            if shop.get("dinner_peak_strong"):
                score += 1

    # ---- 人気度補正 ----
    pop = shop.get("popular_level", 1)
    if pop >= 3:
        score += 1   # 超人気店は常にスコアを押し上げる

    # ---- 回転速度補正（混んでいるときに緩和） ----
    fast = shop.get("fast_turnover", False)
    if fast and score >= 2:
        score -= 1

    # ---- wait_level 決定 ----
    if score <= 0:
        level = "green"
    elif score == 1:
        level = "yellow"
    else:
        level = "red"

    # ---- reason ラベル生成（短文・判断補助） ----
    if level == "green":
        if fast and is_peak:
            reason = "回転が早く、比較的すぐ座れる"
        elif not is_weekend and 14.0 <= t < 17.0:
            reason = "今の時間は空いていることが多い"
        elif is_weekend and not is_peak:
            reason = "土日でもこの時間は並ばず入れることが多い"
        else:
            reason = "今なら並ばず入れる可能性が高い"
    elif level == "yellow":
        if fast:
            reason = "少し待つが、席は比較的早く空きやすい"
        elif is_weekend and is_peak:
            reason = "週末ピーク中のため、5〜10分待つかも"
        elif is_peak:
            reason = "ピーク中のため、5〜10分待ちになることが多い"
        elif pop >= 2:
            reason = "人気店のため、少し並ぶ可能性がある"
        else:
            reason = "5〜10分待つことが多い"
    else:  # red
        if pop >= 3 and is_peak:
            reason = "超人気店のピーク帯、行列は避けにくい"
        elif pop >= 3:
            reason = "常に行列が出やすい人気店"
        elif is_weekend and is_peak:
            reason = "週末ピーク帯、相当の待ちが予想される"
        elif is_peak:
            reason = "今の時間帯は10分以上の待ちになりやすい"
        else:
            reason = "ピーク外でも混みやすく、長め待ちになることが多い"

    return level, reason


# ============================================================
# 店舗データ（池袋駅徒歩圏）
# wait_level は実行時に compute_wait_level() で動的に決定する
# updated_minutes_ago : 最終更新からの経過分数（仮データ）
# report_summary      : ユーザー報告のサマリー（仮データ、None = 報告なし）
# ============================================================
ramen_shops = [
    {
        "name": "つけ麺 道 池袋東口",
        "comment": "濃厚魚介系つけ麺。麺の量が選べる",
        "address": "東京都豊島区東池袋1-6-3",
        "map_url": "https://maps.google.com/?q=つけ麺+道+池袋東口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩2分",
        "walk_minutes": 2,
        "tag": "つけ麺",
        "latitude": 35.7294,
        "longitude": 139.7128,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 11,
        "report_summary": None,
    },
    {
        "name": "博多風龍 池袋店",
        "comment": "替え玉無料の博多豚骨。回転が速い",
        "address": "東京都豊島区西池袋1-15-2",
        "map_url": "https://maps.google.com/?q=博多風龍+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "博多豚骨",
        "latitude": 35.7303,
        "longitude": 139.7079,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 7,
        "report_summary": "空いてた報告あり",
    },
    {
        "name": "無敵家",
        "comment": "濃厚豚骨醤油の名店。行列必至の人気ぶり",
        "address": "東京都豊島区南池袋1-17-1",
        "map_url": "https://maps.google.com/?q=無敵家+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "濃厚豚骨",
        "latitude": 35.7268,
        "longitude": 139.7116,
        "base_crowd_score": 2,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 3,
        "report_summary": "混んでた報告あり",
    },
    {
        "name": "麺屋 武蔵 池袋店",
        "comment": "煮干し系で有名な人気店",
        "address": "東京都豊島区南池袋1-16-10",
        "map_url": "https://maps.google.com/?q=麺屋+武蔵+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "濃厚煮干し",
        "latitude": 35.7270,
        "longitude": 139.7113,
        "base_crowd_score": 2,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 18,
        "report_summary": "やや混み報告あり",
    },
    {
        "name": "ラーメン二郎 池袋東口店",
        "comment": "ボリューム圧倒的。コール必須の二郎インスパイア",
        "address": "東京都豊島区東池袋1-13-12",
        "map_url": "https://maps.google.com/?q=ラーメン二郎+池袋東口店",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "ガッツリ系",
        "latitude": 35.7305,
        "longitude": 139.7148,
        "base_crowd_score": 1,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 6,
        "report_summary": "混んでた報告あり",
    },
    {
        "name": "頑者 池袋店",
        "comment": "鶏の旨みが光る家系ラーメン",
        "address": "東京都豊島区東池袋1-12-6",
        "map_url": "https://maps.google.com/?q=頑者+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "家系",
        "latitude": 35.7306,
        "longitude": 139.7146,
        "base_crowd_score": 2,
        "popular_level": 2,
        "fast_turnover": False,
        "lunch_peak_strong": False,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 22,
        "report_summary": None,
    },
    {
        "name": "らーめん壱角家 池袋西口店",
        "comment": "家系チェーン。安定の味と回転の速さ",
        "address": "東京都豊島区西池袋1-26-5",
        "map_url": "https://maps.app.goo.gl/yMa1wu6yxWn7SDvJA",
        "route_url": "https://maps.app.goo.gl/yMa1wu6yxWn7SDvJA",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "家系",
        "latitude": 35.7314,
        "longitude": 139.7073,
        "base_crowd_score": 0,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 9,
        "report_summary": "空いてた報告あり",
    },
    {
        "name": "らあめん花月嵐 池袋店",
        "comment": "チェーンで安定。期間限定メニューが豊富",
        "address": "東京都豊島区東池袋1-28-5",
        "map_url": "https://maps.google.com/?q=花月嵐+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "チェーン・味噌",
        "latitude": 35.7307,
        "longitude": 139.7153,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 14,
        "report_summary": None,
    },
    {
        "name": "黒帯 池袋店",
        "comment": "濃厚醤油で地元に根強いファンを持つ",
        "address": "東京都豊島区南池袋1-8-4",
        "map_url": "https://maps.google.com/?q=黒帯+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "濃厚醤油",
        "latitude": 35.7264,
        "longitude": 139.7110,
        "base_crowd_score": 2,
        "popular_level": 2,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 8,
        "report_summary": "やや混み報告あり",
    },
    {
        "name": "鶏白湯ラーメン 鳥の庄",
        "comment": "まろやかな鶏白湯。落ち着いた雰囲気",
        "address": "東京都豊島区西池袋3-26-5",
        "map_url": "https://maps.google.com/?q=鶏白湯ラーメン+鳥の庄+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "鶏白湯",
        "latitude": 35.7322,
        "longitude": 139.7062,
        "base_crowd_score": 0,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 26,
        "report_summary": "空いてた報告あり",
    },
    {
        "name": "東京豚骨拉麺 ばんから 池袋店",
        "comment": "ガッツリ豚骨醤油。コスパが高い",
        "address": "東京都豊島区東池袋1-23-14",
        "map_url": "https://maps.google.com/?q=ばんから+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "豚骨醤油",
        "latitude": 35.7309,
        "longitude": 139.7158,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 5,
        "report_summary": None,
    },
    {
        "name": "麺屋 こころ 池袋",
        "comment": "醤油ベースの奥深いスープが特徴",
        "address": "東京都豊島区東池袋2-3-7",
        "map_url": "https://maps.google.com/?q=麺屋+こころ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "醤油ラーメン",
        "latitude": 35.7268,
        "longitude": 139.7155,
        "base_crowd_score": 2,
        "popular_level": 2,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 17,
        "report_summary": "やや混み報告あり",
    },
    {
        "name": "らーめん 天下一品 池袋東口店",
        "comment": "こってりスープの代名詞。根強い常連客が多い",
        "address": "東京都豊島区東池袋1-42-16",
        "map_url": "https://maps.google.com/?q=天下一品+池袋東口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "こってり",
        "latitude": 35.7277,
        "longitude": 139.7162,
        "base_crowd_score": 2,
        "popular_level": 2,
        "fast_turnover": True,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 12,
        "report_summary": None,
    },
    {
        "name": "池袋大勝軒",
        "comment": "元祖もりそばの流れを汲む一軒",
        "address": "東京都豊島区南池袋2-42-7",
        "map_url": "https://maps.google.com/?q=池袋大勝軒",
        "is_open": True,
        "walk_time": "池袋駅から徒歩7分",
        "walk_minutes": 7,
        "tag": "もりそば・つけ麺",
        "latitude": 35.7252,
        "longitude": 139.7120,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 33,
        "report_summary": "空いてた報告あり",
    },
    {
        "name": "北海道らーめん 札幌や 池袋",
        "comment": "本場札幌仕込みの味噌ラーメン",
        "address": "東京都豊島区西池袋3-30-9",
        "map_url": "https://maps.google.com/?q=札幌や+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩7分",
        "walk_minutes": 7,
        "tag": "北海道味噌",
        "latitude": 35.7316,
        "longitude": 139.7056,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 21,
        "report_summary": None,
    },
    {
        "name": "麺屋 一燈 池袋",
        "comment": "煮干し醤油の名店。遠方から来る人も多い",
        "address": "東京都豊島区南池袋2-26-7",
        "map_url": "https://maps.google.com/?q=麺屋+一燈+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "煮干し醤油",
        "latitude": 35.7248,
        "longitude": 139.7128,
        "base_crowd_score": 2,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 8,
        "report_summary": "混んでた報告あり",
    },
    {
        "name": "凪 煮干しそば 池袋",
        "comment": "煮干し特化の有名店。独特の濃厚スープ",
        "address": "東京都豊島区南池袋2-7-11",
        "map_url": "https://maps.google.com/?q=凪+煮干しそば+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "煮干し",
        "latitude": 35.7256,
        "longitude": 139.7117,
        "base_crowd_score": 2,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 15,
        "report_summary": "やや混み報告あり",
    },
    {
        "name": "ソラノイロ 池袋",
        "comment": "ベジそばでも有名。あっさり塩が穴場",
        "address": "東京都豊島区南池袋2-18-5",
        "map_url": "https://maps.google.com/?q=ソラノイロ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "ベジ・塩",
        "latitude": 35.7250,
        "longitude": 139.7125,
        "base_crowd_score": 0,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 38,
        "report_summary": None,
    },
    {
        "name": "麺処 花田 池袋店",
        "comment": "北海道味噌を丁寧に仕上げた一杯",
        "address": "東京都豊島区東池袋2-14-3",
        "map_url": "https://maps.google.com/?q=麺処+花田+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "味噌ラーメン",
        "latitude": 35.7275,
        "longitude": 139.7178,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 10,
        "report_summary": None,
    },
    {
        "name": "麺や 七彩 池袋",
        "comment": "丁寧な手打ち麺が名物。回転はゆっくり",
        "address": "東京都豊島区東池袋2-56-3",
        "map_url": "https://maps.google.com/?q=麺や+七彩+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "手打ち中華そば",
        "latitude": 35.7270,
        "longitude": 139.7180,
        "base_crowd_score": 2,
        "popular_level": 2,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 19,
        "report_summary": "やや混み報告あり",
    },
    {
        "name": "塩そば 彩 池袋",
        "comment": "鶏と昆布の澄んだ塩スープ",
        "address": "東京都豊島区東池袋2-8-11",
        "map_url": "https://maps.google.com/?q=塩そば+彩+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "あっさり塩",
        "latitude": 35.7272,
        "longitude": 139.7173,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 42,
        "report_summary": None,
    },
    {
        "name": "中華そば 青葉 池袋",
        "comment": "ダブルスープの草分け的存在",
        "address": "東京都豊島区南池袋3-12-8",
        "map_url": "https://maps.google.com/?q=中華そば+青葉+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩10分",
        "walk_minutes": 10,
        "tag": "中華そば",
        "latitude": 35.7240,
        "longitude": 139.7128,
        "base_crowd_score": 1,
        "popular_level": 2,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 7,
        "report_summary": None,
    },
    {
        "name": "麺家 うえだ 池袋",
        "comment": "煮干し醤油の地元密着店",
        "address": "東京都豊島区西池袋2-42-3",
        "map_url": "https://maps.google.com/?q=麺家+うえだ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩10分",
        "walk_minutes": 10,
        "tag": "煮干し醤油",
        "latitude": 35.7325,
        "longitude": 139.7044,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 28,
        "report_summary": "空いてた報告あり",
    },
    {
        "name": "担々麺 吉虎 池袋",
        "comment": "本格四川担々麺。辛さが選べる",
        "address": "東京都豊島区西池袋4-5-9",
        "map_url": "https://maps.google.com/?q=担々麺+吉虎+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩11分",
        "walk_minutes": 11,
        "tag": "担々麺",
        "latitude": 35.7332,
        "longitude": 139.7035,
        "base_crowd_score": 0,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": False,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 55,
        "report_summary": None,
    },
    {
        "name": "とんこつラーメン 天神 池袋",
        "comment": "博多直系の豚骨。夜は特に賑わう",
        "address": "東京都豊島区東池袋3-8-12",
        "map_url": "https://maps.google.com/?q=とんこつラーメン+天神+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩12分",
        "walk_minutes": 12,
        "tag": "博多豚骨",
        "latitude": 35.7280,
        "longitude": 139.7198,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": False,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 13,
        "report_summary": None,
    },
    {
        "name": "麺屋 龍之介 池袋",
        "comment": "透き通った鶏清湯が自慢",
        "address": "東京都豊島区南池袋3-24-5",
        "map_url": "https://maps.google.com/?q=麺屋+龍之介+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩12分",
        "walk_minutes": 12,
        "tag": "鶏清湯",
        "latitude": 35.7232,
        "longitude": 139.7132,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 24,
        "report_summary": None,
    },
    {
        "name": "東池袋大勝軒 本店",
        "comment": "つけ麺発祥の地として有名な聖地",
        "address": "東京都豊島区東池袋4-28-3",
        "map_url": "https://maps.google.com/?q=東池袋大勝軒+本店",
        "is_open": True,
        "walk_time": "池袋駅から徒歩13分",
        "walk_minutes": 13,
        "tag": "元祖つけ麺",
        "latitude": 35.7284,
        "longitude": 139.7213,
        "base_crowd_score": 2,
        "popular_level": 3,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": True,
        "updated_minutes_ago": 6,
        "report_summary": "混んでた報告あり",
    }
]


@app.route("/")
def index():
    return render_template("index.html", area_name=AREA_NAME)


@app.route("/result")
def result():
    max_walk_str = request.args.get("max_walk")
    mode = request.args.get("mode", "")

    # 現在時刻をもとに全店舗の wait_level と reason を動的に計算
    now = datetime.now()
    enriched = []
    for shop in ramen_shops:
        s = dict(shop)
        s["wait_level"], s["reason"] = compute_wait_level(s, now)
        s["area"] = s.get("area", AREA_NAME)
        if not s.get("route_url"):
            s["route_url"] = "https://www.google.com/maps/dir/?api=1&destination=" + quote(s["address"]) + "&travelmode=walking"
        enriched.append(s)

    # 徒歩圏フィルタ
    if max_walk_str and max_walk_str.isdigit():
        max_walk = int(max_walk_str)
        filtered = [s for s in enriched if s["walk_minutes"] <= max_walk]
        filter_label = f"池袋駅から徒歩{max_walk}分以内の営業中店舗"
    else:
        max_walk = None
        filtered = enriched
        filter_label = "池袋駅周辺の営業中店舗"

    # 営業中のみ表示（デフォルト動作）
    # 将来 "閉店中も含む" 表示が必要になった場合は、ここで条件を分岐させる
    filtered = [s for s in filtered if s["is_open"]]

    # 待ちレベル・徒歩分数の順でソート（JS未使用時のフォールバック）
    filtered.sort(key=sort_key)

    total_count = len(filtered)

    # 表示件数を上限に制限（MAX_DISPLAY を変更するだけで調整可能）
    displayed = filtered[:MAX_DISPLAY]

    # おすすめスコアで「今行くならここ」店舗を選定
    if displayed:
        featured_shop = max(displayed, key=compute_recommend_score)
        other_shops   = [s for s in displayed if s is not featured_shop]
    else:
        featured_shop = None
        other_shops   = []

    return render_template(
        "result.html",
        featured_shop=featured_shop,
        other_shops=other_shops,
        all_shops_json=filtered,   # JS の現在地ソートに使用（全件・フィルタ済み）
        filter_label=filter_label,
        max_walk=max_walk,
        mode=mode,
        total_count=total_count,
        max_display=MAX_DISPLAY,
        area_name=AREA_NAME,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
