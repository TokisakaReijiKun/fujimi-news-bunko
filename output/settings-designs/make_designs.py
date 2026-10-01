from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import textwrap, math

OUT = Path('output/settings-designs')
OUT.mkdir(parents=True, exist_ok=True)
W, H = 780, 1760

FONT_REG = r'C:\Windows\Fonts\NotoSansJP-VF.ttf'
FONT_SERIF = r'C:\Windows\Fonts\NotoSerifJP-VF.ttf'

def font(size, bold=False, serif=False):
    path = FONT_SERIF if serif else FONT_REG
    return ImageFont.truetype(path, size=size)

def rounded(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def txt(draw, xy, s, size=24, fill='#18342d', bold=False, serif=False, anchor='la'):
    draw.text(xy, s, font=font(size, bold=bold, serif=serif), fill=fill, anchor=anchor)

def line(draw, xy, fill='#d9e2dd', width=2):
    draw.line(xy, fill=fill, width=width)

def pill(draw, x, y, label, fill, fg, w=None):
    f = font(20)
    bbox = draw.textbbox((0,0), label, font=f)
    tw = bbox[2]-bbox[0]
    width = w or tw + 28
    rounded(draw, (x,y,x+width,y+42), 21, fill)
    txt(draw,(x+width/2,y+21),label,20,fg,anchor='mm')
    return width

def section_title(draw, y, index, title, sub, accent, dark='#17342d'):
    txt(draw, (56,y), f'{index:02d}', 20, accent, bold=True)
    txt(draw, (104,y-1), title, 29, dark, bold=True)
    if sub: txt(draw, (104,y+38), sub, 18, '#71837b')

def toggle(draw, x,y,on=True, color='#287d66'):
    rounded(draw,(x,y,x+88,y+48),24,color if on else '#c6d1cc')
    draw.ellipse((x+(53 if on else 5),y+5,x+(83 if on else 35),y+35),fill='#fff')

def checkbox(draw,x,y,checked=True,color='#287d66'):
    rounded(draw,(x,y,x+34,y+34),8,color if checked else '#fff', outline=color, width=2)
    if checked:
        line(draw,(x+8,y+17,x+15,y+24), '#fff', 4)
        line(draw,(x+15,y+24,x+27,y+10), '#fff', 4)

def draw_a():
    bg='#f3f1ea'; ink='#16342d'; muted='#71817a'; green='#2e7d68'; pale='#e2eee8'; card='#fffdf9'; rule='#d7e0db'; amber='#e9b86d'
    im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
    # top
    txt(d,(56,58),'富士見新聞文庫',24,green,bold=True)
    txt(d,(56,98),'設定',48,ink,bold=True)
    txt(d,(56,156),'読む時間を、自分らしく整える。',21,muted)
    rounded(d,(560,54,724,118),32,green)
    txt(d,(642,86),'保存済み',19,'#ffffff',bold=True,anchor='mm')
    line(d,(56,202,724,202),rule,2)
    # summary card
    rounded(d,(56,236,724,430),28,ink)
    txt(d,(88,276),'今日の読み方',18,'#b9d5c8',bold=True)
    txt(d,(88,320),'静かな音声で',31,'#fffdf9',bold=True)
    txt(d,(88,362),'毎朝 07:30 に日刊を生成',31,'#fffdf9',bold=True)
    pill(d,88,394,'Android 本地', '#3d8c75','#f7fffb')
    pill(d,270,394,'CST / 自動更新', '#3d8c75','#f7fffb')
    # voice
    section_title(d,492,1,'声の形','読み上げに使う声を選択',green,ink)
    rounded(d,(56,594,724,704),24,card,rule,2)
    txt(d,(88,630),'システム日語音声',22,ink,bold=True)
    txt(d,(88,669),'ja · 使用中',18,muted)
    txt(d,(612,646),'選択再生',18,green,bold=True,anchor='ra')
    line(d,(88,692,692,692),rule,2)
    txt(d,(88,744),'実際に発声して確認',18,muted)
    rounded(d,(88,776,310,832),28,pale)
    txt(d,(199,804),'▶  サンプル再生',19,green,bold=True,anchor='mm')
    # daily
    section_title(d,890,2,'日刊設定','来源・配额・生成方式',green,ink)
    rounded(d,(56,986,724,1248),24,card,rule,2)
    txt(d,(88,1024),'每日新聞目標数',19,muted)
    txt(d,(88,1065),'10',38,ink,bold=True)
    txt(d,(622,1066),'篇 / 日',19,muted,anchor='ra')
    line(d,(88,1112,692,1112),rule,2)
    txt(d,(88,1146),'ニュースソース',19,muted)
    txt(d,(622,1146),'6 个来源',19,green,bold=True,anchor='ra')
    line(d,(88,1192,692,1192),rule,2)
    txt(d,(88,1226),'生成方式',19,muted)
    txt(d,(622,1226),'手動生成',19,green,bold=True,anchor='ra')
    # shelf
    section_title(d,1304,3,'書架表示','阅读时优先显示什么',green,ink)
    rounded(d,(56,1400,724,1494),24,card,rule,2)
    txt(d,(88,1432),'排序',18,muted)
    txt(d,(88,1469),'最近読んだ順',22,ink,bold=True)
    txt(d,(680,1469),'v',27,green,bold=True,anchor='ra')
    # sync teaser
    section_title(d,1554,4,'PC 協同','按需同步，不自动打扰',green,ink)
    rounded(d,(56,1648,724,1718),24,green)
    txt(d,(390,1683),'立即同步  ·  未连接',21,'#fff',bold=True,anchor='mm')
    im.save(OUT/'design-a-editorial-cards.png')

def draw_b():
    bg='#f6f8f7'; ink='#1b2b3b'; muted='#72808c'; navy='#203246'; coral='#da755f'; linec='#dce4e8'; white='#ffffff'; blue='#4d718b'
    im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
    # header/nav
    rounded(d,(0,0,W,260),0,navy)
    txt(d,(56,54),'PREFERENCES',18,'#b8c6d2',bold=True)
    txt(d,(56,92),'設定',50,'#ffffff',bold=True)
    txt(d,(56,158),'内容、设备与同步',22,'#d9e3ea')
    pill(d,56,198,'1 个提醒', '#334961','#f7fbff')
    # nav tabs
    rounded(d,(40,282,740,356),30,white,linec,2)
    for i,(lab,x,active) in enumerate([('阅读',64,False),('内容',220,True),('设备',376,False),('同步',532,False)]):
        if active: rounded(d,(x-14,294,x+98,344),24,'#edf3f5')
        txt(d,(x+42,319),lab,20,navy if active else muted,bold=active,anchor='mm')
    # card helper
    def card(y,h,title,sub=None):
        rounded(d,(40,y,740,y+h),26,white,linec,2)
        txt(d,(72,y+34),title,26,navy,bold=True)
        if sub: txt(d,(72,y+76),sub,18,muted)
    card(392,236,'日刊设置','每天 07:30 · CST')
    txt(d,(72,510),'目标数',18,muted); txt(d,(650,508),'10 篇',28,navy,bold=True,anchor='ra')
    line(d,(72,548,708,548),linec,2)
    txt(d,(72,584),'ニュースソース',18,muted); txt(d,(650,584),'6 个来源',20,blue,bold=True,anchor='ra')
    card(664,258,'朗读','默认使用实际选中的系统日语声线')
    txt(d,(72,784),'システム日語音声',22,navy,bold=True)
    txt(d,(72,820),'ja · 使用中',18,muted)
    toggle(d,592,790,True,coral)
    rounded(d,(72,858,708,906),24,'#fff4ef')
    txt(d,(390,882),'▶  试听当前声线',18,coral,bold=True,anchor='mm')
    card(958,246,'书架','打开书籍时的默认位置')
    txt(d,(72,1072),'排序方式',18,muted); txt(d,(72,1115),'最近読んだ順',22,navy,bold=True)
    txt(d,(676,1115),'v',26,blue,bold=True,anchor='ra')
    card(1244,282,'设备与密钥','本机运行状态')
    txt(d,(72,1350),'Android 本地节点',21,navy,bold=True); pill(d,564,1333,'可用', '#e9f5f2',blue)
    txt(d,(72,1400),'DeepSeek',21,navy,bold=True); txt(d,(650,1400),'未配置',19,muted,anchor='ra')
    card(1560,148,'同步','PC 協同 · 未连接')
    rounded(d,(72,1642,708,1698),28,navy)
    txt(d,(390,1670),'立即同步',20,'#ffffff',bold=True,anchor='mm')
    im.save(OUT/'design-b-quiet-tabs.png')

def draw_c():
    bg='#f0eee8'; ink='#18202a'; muted='#7b7c76'; indigo='#30466f'; verm='#b75b4c'; paper='#fffdfa'; rule='#ddd9cf'; pale='#e9e6dd'
    im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
    # editorial masthead
    txt(d,(52,50),'FUJIMI / READING SETTINGS',17,indigo,bold=True)
    txt(d,(52,94),'設定',54,ink,bold=True,serif=True)
    txt(d,(52,166),'毎日読むための、小さな編集部。',21,muted,serif=True)
    rounded(d,(642,56,724,138),41,verm)
    txt(d,(683,97),'✓',34,'#fff',bold=True,anchor='mm')
    line(d,(52,220,728,220),indigo,4)
    # index strip
    txt(d,(52,252),'INDEX',16,verm,bold=True)
    txt(d,(160,252),'声',18,ink,bold=True); txt(d,(254,252),'日刊',18,ink,bold=True); txt(d,(370,252),'書架',18,ink,bold=True); txt(d,(486,252),'同期',18,ink,bold=True)
    line(d,(52,286,728,286),rule,2)
    # two-column style blocks
    section_title(d,334,1,'声の形','系统日语声线',verm,ink)
    rounded(d,(52,432,728,584),0,paper,rule,2)
    txt(d,(80,468),'システム日語音声',23,ink,bold=True)
    txt(d,(80,510),'ja · 使用中',18,muted)
    rounded(d,(548,462,692,530),0,indigo)
    txt(d,(620,496),'試聴',19,'#fff',bold=True,anchor='mm')
    line(d,(80,552,692,552),rule,2)
    txt(d,(80,570),'选中的声线用于文章、书籍和词典即时朗读。',17,muted)
    section_title(d,650,2,'日刊','每天的来源与生成规则',verm,ink)
    rounded(d,(52,748,728,1026),0,paper,rule,2)
    txt(d,(80,788),'每日新聞目標数',18,muted)
    txt(d,(80,836),'10',42,indigo,bold=True)
    txt(d,(184,837),'篇',22,muted)
    line(d,(80,892,692,892),rule,2)
    txt(d,(80,930),'ニュースソース',18,muted); txt(d,(692,930),'6 个来源',19,indigo,bold=True,anchor='ra')
    line(d,(80,968,692,968),rule,2)
    txt(d,(80,1005),'生成方式',18,muted); txt(d,(692,1005),'手動生成',19,verm,bold=True,anchor='ra')
    section_title(d,1094,3,'書架','恢复阅读的默认方式',verm,ink)
    rounded(d,(52,1192,728,1324),0,paper,rule,2)
    txt(d,(80,1230),'打开书籍',18,muted)
    txt(d,(80,1274),'书签优先，其次恢复本机进度',22,ink,bold=True)
    txt(d,(692,1274),'>',27,verm,bold=True,anchor='ra')
    section_title(d,1390,4,'同期','PC 協同与文庫维护',verm,ink)
    rounded(d,(52,1488,728,1696),0,paper,rule,2)
    txt(d,(80,1528),'PC 協同',21,ink,bold=True); txt(d,(692,1528),'未连接',18,muted,anchor='ra')
    line(d,(80,1568,692,1568),rule,2)
    txt(d,(80,1604),'文庫刷新',21,ink,bold=True); txt(d,(692,1604),'FILES → INDEX',17,indigo,bold=True,anchor='ra')
    rounded(d,(80,1634,700,1680),0,indigo)
    txt(d,(390,1657),'立即同步 / 反映存储',18,'#fff',bold=True,anchor='mm')
    im.save(OUT/'design-c-editorial-masthead.png')

for fn in (draw_a, draw_b, draw_c): fn()
print('\n'.join(str(p.resolve()) for p in sorted(OUT.glob('*.png'))))

