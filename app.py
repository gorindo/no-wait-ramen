from flask import Flask, render_template

app = Flask(__name__)

# 仮データ（ハードコード）
ramen_shops = [
    {
        "name": "ラーメン二郎 池袋東口店",
        "wait_level": "green",
        "comment": "今ならスッと入れる",
        "address": "東京都豊島区東池袋1-13-12",
        "map_url": "https://maps.google.com/?q=ラーメン二郎+池袋東口店",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "tag": "ガッツリ系"
    },
    {
        "name": "無敵家",
        "wait_level": "yellow",
        "comment": "5分くらいでいけそう",
        "address": "東京都豊島区南池袋1-17-1",
        "map_url": "https://maps.google.com/?q=無敵家+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "tag": "濃厚豚骨"
    },
    {
        "name": "麺創房 無敵家 別館",
        "wait_level": "red",
        "comment": "今はちょい混み",
        "address": "東京都豊島区南池袋1-21-5",
        "map_url": "https://maps.google.com/?q=麺創房+無敵家+別館+池袋",
        "is_open": False,
        "walk_time": "池袋駅から徒歩5分",
        "tag": "あっさり醤油"
    }
]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/result")
def result():
    return render_template("result.html", shops=ramen_shops)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
