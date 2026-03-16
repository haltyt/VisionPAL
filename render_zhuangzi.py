#!/usr/bin/env python3
"""Render Zhuangzi research summary as PNG using PIL."""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 800, 1250
img = Image.new("RGB", (W, H), "#0f0f23")
d = ImageDraw.Draw(img)

# Fonts
home = os.path.expanduser("~")
jp_font = os.path.join(home, ".fonts", "NotoSansCJKjp-Regular.otf")
jp_serif = os.path.join(home, ".fonts", "NotoSerifCJKjp-Regular.otf")

def font(size, serif=False):
    path = jp_serif if serif else jp_font
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()

def wrap(text, f, max_w):
    lines = []
    for line in text.split('\n'):
        cur = ""
        for ch in line:
            test = cur + ch
            bbox = d.textbbox((0,0), test, font=f)
            if bbox[2] - bbox[0] > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    return lines

# Colors
purple = "#a78bfa"
light_purple = "#c4b5fd"
indigo = "#818cf8"
gray = "#9ca3af"
dark_gray = "#7c7c9e"
text_color = "#b4b4ce"
card_bg = (255, 255, 255, 10)

y = 30

# Title
f_title = font(24, serif=True)
f_sub = font(12)
d.text((W//2, y), "🦋", font=font(32), fill=purple, anchor="mt")
y += 48
d.text((W//2, y), "荘子リサーチ #1 — 胡蝶の夢", font=f_title, fill=purple, anchor="mt")
y += 32
d.text((W//2, y), "斉物論篇 × 現代テクノロジー｜2026.02.25", font=f_sub, fill=dark_gray, anchor="mt")
y += 28

# Quote box
d.rectangle([40, y, 760, y+165], fill=(167,139,250,15))
d.rectangle([40, y, 43, y+165], fill=purple)

qy = y + 16
f_chinese = font(13, serif=True)
chinese_lines = [
    "昔者莊周夢爲胡蝶、栩栩然胡蝶也。自喻適志與、不知周也。",
    "俄然覺、則蘧蘧然周也。不知周之夢爲胡蝶與、胡蝶之夢爲周與。",
    "周與胡蝶、則必有分矣。此之謂物化。",
]
for line in chinese_lines:
    d.text((60, qy), line, font=f_chinese, fill=light_purple)
    qy += 22
qy += 10
f_jp = font(11)
jp_lines = [
    "かつて荘周は夢の中で蝶になった。ひらひらと楽しげな蝶そのものだった。",
    "自分が荘周であることなど知らなかった。ふと目覚めると、まぎれもなく荘周である。",
    "荘周が夢で蝶になったのか、蝶が夢で荘周になっているのか——これを「物化」という。",
]
for line in jp_lines:
    d.text((60, qy), line, font=f_jp, fill=gray)
    qy += 18
y += 175

# Section header
y += 12
f_section = font(16)
d.text((40, y), "📚 関連研究 (2024–2026)", font=f_section, fill=purple)
y += 24
d.line([(40, y), (760, y)], fill=(167,139,250,50), width=1)
y += 10

# Papers
papers = [
    ("1. Mastering the Body: Embodiment in the Zhuangzi",
     "L. Ko — Religion Compass, 2025",
     "荘子の「技の達人」物語群を身体化の観点で分析。身体・心・気・精神の全体的調和哲学。"),
    ("2. Mind, Machine, and Being — The Nature of Consciousness",
     "X. Wu — PhilPapers, 2026",
     "荘子の「知魚楽」から意識・AI・身体性を学際的に探究。「準身体的知能モデル」を提案。"),
    ("3. Contemplation and Computation: Art, Image, and Reality",
     "G. Polmeer — Springer, 2024",
     "胡蝶の夢×VR/仮想世界。デジタル没入体験と「夢と覚醒の曖昧さ」の比較研究。"),
    ("4. Zhuangzi's Fish Parable and Merleau-Ponty",
     "K. Zhu — Metaphilosophy 55(2), 2024",
     "相関的思考の身体性を解明。AI訓練における他者理解モデルへの示唆。"),
    ("5. AI and Consciousness",
     "E. Schwitzgebel — arXiv:2510.09858, 2025",
     "AI意識の懐疑的概観。意識理論次第で「ある」とも「ない」とも——判定不能の時代。"),
]
f_ptitle = font(12)
f_pmeta = font(10)
f_pdesc = font(10)
for title, meta, desc in papers:
    d.rounded_rectangle([40, y, 760, y+62], radius=6, fill=(255,255,255,10))
    d.text((56, y+10), title, font=f_ptitle, fill=light_purple)
    d.text((56, y+28), meta, font=f_pmeta, fill=dark_gray)
    d.text((56, y+44), desc, font=f_pdesc, fill=gray)
    y += 72

# Insights
y += 8
d.text((40, y), "💡 考察：荘子 × 現代テクノロジー", font=f_section, fill=purple)
y += 24
d.line([(40, y), (760, y)], fill=(167,139,250,50), width=1)
y += 10

insights = [
    ("🥽 VR/XR — 2600年前のシミュレーション仮説",
     ["VR没入時に「自分を忘れる」体験は「不知周也」そのもの。",
      "ハルトのXR作品——現実と仮想の境界を溶かす——は物化の思想と深く共鳴する。"]),
    ("🤖 AI意識 — 夢の蝶は本物か？",
     ["AIが感情を表現するとき、それは本物？夢の蝶？荘子なら「どちらが本物か」",
      "ではなく、変容のプロセス＝「物化」として捉える。固定された正解はない。"]),
    ("🔄 物化 — AI学習もまた変容",
     ["データから知識への変容、モデルの重みが「何か」を理解し始める瞬間。",
      "蝶になった荘周のように、変容の中にこそ本質がある。"]),
]
f_ititle = font(12)
f_idesc = font(11)
for title, lines in insights:
    d.rounded_rectangle([40, y, 760, y+68], radius=10, fill=(99,102,241,20))
    d.text((56, y+12), title, font=f_ititle, fill=indigo)
    ly = y + 32
    for line in lines:
        d.text((56, ly), line, font=f_idesc, fill=text_color)
        ly += 18
    y += 78

# Footer
y += 12
d.line([(40, y), (760, y)], fill=(167,139,250,25), width=1)
y += 12
d.text((W//2, y), "🐾 パル — 荘子リサーチシリーズ｜古代思想と最新テクノロジーの交差点を探る", font=f_sub, fill=dark_gray, anchor="mt")

out = "/home/node/.openclaw/workspace/zhuangzi_summary.png"
img.save(out, "PNG")
print(f"SAVED: {out}")
