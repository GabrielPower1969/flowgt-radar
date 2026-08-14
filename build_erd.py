"""生成 erd.html —— 数据库全景：ERD、schema、设计原则、ETL 流向。

    python3 build_erd.py

沿用 pipeline.html 的设计令牌：两份是配套文档，不该长得不一样。
Shares pipeline.html's tokens; they are companion documents.
"""
import html
import json
import pathlib
import re

import schema_model

HERE = pathlib.Path(__file__).resolve().parent
SITE = HERE.parent / 'flowgt-website'

# ── 产物写到哪 / where the artefact goes ──────────────────────────────────────
#
# 生成器留在这个仓库（它要读 ../flowgt-website 的 schema 和 migrations），
# 产物写到 flowgt-workspace/05-architecture/ —— 那是【回顾用的东西】的唯一入口。
#
# 不在两边各留一份：CLAUDE.md 第七节写着「每样东西只有一个家，没有一句话说
# 两遍 —— 那才是能找到的原因」。两份 HTML 迟早有一份先旧，而旧的那份不会报错。
#
# The generator stays here, where its inputs are; the artefact goes to the one
# place meant for reviewing. Not both: two copies means one of them goes stale
# first, and the stale one does not raise.
ARCH = HERE.parent / 'flowgt-workspace' / '05-architecture'


M = schema_model.build()
TABLES, DOMAINS, INDEXES = M['tables'], M['domains'], M['indexes']


# ── 迁移历史：设计记录本身 ────────────────────────────────────────────────────
def migrations():
    out = []
    for f in sorted((SITE / 'migrations').glob('*.sql')):
        head = f.read_text(encoding='utf-8', errors='ignore').split('\n')[:6]
        title = ''
        for l in head[:3]:
            t = re.sub(r'^--\s*\d*\s*[·—-]?\s*', '', l).strip()
            if t and not t.lower().startswith('apply'):
                title = t
                break
        out.append({'id': f.stem, 'title': title})
    return out


MIGRATIONS = migrations()

# 设计原则 —— 每一条都指向一个真实的迁移文件，不是我现编的。
# 「有出处」和「听起来对」是两件事，后者是这个仓库最不需要的东西。
PRINCIPLES = [
    ('约束下沉到数据库，不留在「应用层自觉」', '0003-constraints',
     '2026-08-05 的自洽性测试查了 10 项，真实数据全过 —— 但逐条注入违规行之后发现'
     '<b>其中 9 项根本没有约束在守</b>。<code>tier=\'banana\'</code>、'
     '<code>email=\'\'</code>、<code>created_at</code> 在 2099 年、一个账号挂三条邮箱身份，'
     'SQLite 全部照收。一个只靠代码记得的不变量，不是不变量。'),
    ('一列只干一件事', '0004-roles-and-plans',
     '<code>tier</code> 原本同时表示「这个人证明过自己拥有这个邮箱」（身份）和'
     '「他的配额是 50 不是 5」（权益）。这两件事会各自独立地变：'
     'VIP 到期了身份还在，新用户身份验过了权益还是免费。合在一列里，'
     '任何一边变化都要小心不要碰坏另一边。'),
    ('为一年后的问题建模，不为明天的邮件', '0005-job-market',
     '这份 schema 回答的是「Data Engineer 这个方向 Q3 比 Q2 多了还是少了」。'
     '所以职位名在<b>入库那一刻</b>归一化 —— 一年后再想聚合就晚了，'
     '原始标题里的 <code>Snr. Dev (Contract)</code> 谁也数不清。'),
    ('同意要有证据，不是一个布尔', '0006-subscriptions',
     'UEMA 2007 s 9(3) 把举证责任压在发送方。一年后 DIA 问起来，表里一个 '
     '<code>enabled=1</code> 什么都证明不了。要能答三件事：他<b>什么时候</b>打开的、'
     '从<b>哪里</b>打开的、他当时同意的是<b>哪一句话</b>。最后一条最容易漏 —— '
     '同意是针对某个用途的。'),
    ('两个不同的问题，用两把不同的键', '0007-job-deliveries',
     '<code>job_sends</code> 防的是「同一天同一档重复发信」，键是 '
     '<code>(账号, 日期, 档)</code>；<code>job_deliveries</code> 防的是'
     '「同一个岗位出现在两封信里」，键是 <code>(账号, 岗位)</code> —— '
     '<b>刻意不带日期</b>，因为「今天发过了」和「这辈子发过了」是两件事。'),
    ('形状相同就一张表', '0010-resources',
     '周报、AI 信息、播客三个功能形状完全一样：标题、摘要、链接、发布时间、可见门槛。'
     '拆成三张表等于三套 API、三个后台界面、三份 bug。'),
    ('判断在写入时定下，不在读取时算', '0019-role-group',
     '月报要回答「2026 年 8 月 AI 岗位占多少」—— 那必须是<b>当时</b>的判断。'
     '分组规则会不断优化，事后重算等于用今天的尺子量去年的市场，'
     '趋势线会跟着规则动，那条线就没有意义了。'),
    ('不许编数据：假的时间戳比没有时间戳危险得多', '0018-posted-at-was-a-lie',
     '2026-08-09，一封「今日岗位」邮件里 12 个岗位没有一个是当天的，'
     '会员点进 Seek 看到「Posted 6d ago」。根因是解析失败时回落到「我们抓它的时刻」，'
     '于是<b>全库看起来都是 0 天新</b>。现在解析不出来就是 <code>NULL</code> —— '
     '没有的时候，你至少知道自己不知道。'),
    ('做错了就删掉，哪怕它已经上线', '0017-drop-marketplace',
     '会员闲置和暗标拍卖建好了、测过了、上线了，然后在 2026-08-09 被整个删掉：'
     '<b>市场需要流动性，十四个人构不成市场。</b>'),
    ('「跑了，但什么都没有」也必须留痕', '0024-digest-runs',
     '<code>job_sends</code> 只在真的发出一封信时写行 —— 于是「今天没有新岗位所以没发」'
     '在库里<b>和「定时器根本没跑」长得一模一样</b>。'
     '这条原则在 2026-08-14 又被考了一次：三档全员 quiet、48 人次没收到信、两天没人知道。'
     'digest_runs 记下了 quiet，但没有任何东西<b>看</b>它 —— 所以那天补了告警。'),
]


# ── mermaid ──────────────────────────────────────────────────────────────────
def mermaid_for(domain):
    """一个域一张 ERD。跨域的表用虚框表示，只画关系不列字段。"""
    names = set(domain['tables'])
    lines = ['erDiagram']
    ext = set()
    for t in domain['tables']:
        for fk in TABLES[t]['fks']:
            if fk['table'] not in names and fk['table'] in TABLES:
                ext.add(fk['table'])

    for t in domain['tables']:
        tt = TABLES[t]
        lines.append(f'  {t} {{')
        for c in tt['columns']:
            typ = {'INTEGER': 'int', 'TEXT': 'text', 'REAL': 'real',
                   'BLOB': 'blob', 'NUMERIC': 'num'}.get(c['type'], 'text')
            marks = []
            if c['name'] in tt['pk']:
                marks.append('PK')
            if any(c['name'] in fk['from'] for fk in tt['fks']):
                marks.append('FK')
            if c['unique']:
                marks.append('UK')
            tag = ' ' + ','.join(marks) if marks else ''
            lines.append(f'    {typ} {c["name"]}{tag}')
        lines.append('  }')
    for t in sorted(ext):
        lines.append(f'  {t} {{')
        lines.append('    text _ "（别的域）"')
        lines.append('  }')

    for t in domain['tables']:
        for fk in TABLES[t]['fks']:
            if fk['table'] not in TABLES:
                continue
            label = 'CASCADE' if fk['onDelete'] == 'CASCADE' else (
                'SET NULL' if fk['onDelete'] == 'SET NULL' else 'ref')
            lines.append(f'  {fk["table"]} ||--o{{ {t} : "{label}"')
    return '\n'.join(lines)


def overview_mermaid():
    """全局图：只画域和域之间的连线，不画字段。32 张表的字段图没人看得懂。"""
    lines = ['graph TD']
    dom_of = {}
    for d in DOMAINS:
        for t in d['tables']:
            dom_of[t] = d['key']
    for d in DOMAINS:
        rows = sum(TABLES[t]['rows'] for t in d['tables'])
        short = d['title'].split(' / ')[0]
        # 子图 id 前缀 dom_ —— 不能和表名撞。域 key 'resources' 和表名
        # 'resources' 同名时 mermaid 会报 "would create a cycle"，
        # 而那句错误信息完全看不出根因是重名。
        # Prefix subgraph ids: a subgraph sharing a node's id makes mermaid throw
        # "would create a cycle", which says nothing about the actual collision.
        lines.append(f'  subgraph dom_{d["key"]}["{short} · {len(d["tables"])} 表 · {rows:,} 行"]')
        for t in d['tables']:
            lines.append(f'    {t}["{t}<br/><small>{TABLES[t]["rows"]:,}</small>"]')
        lines.append('  end')
    seen = set()
    for t, tt in TABLES.items():
        for fk in tt['fks']:
            if fk['table'] in TABLES:
                k = (fk['table'], t)
                if k in seen:
                    continue
                seen.add(k)
                lines.append(f'  {fk["table"]} --> {t}')
    return '\n'.join(lines)


def etl_mermaid():
    return '''graph LR
  seek["Seek 网页<br/><small>HTML</small>"] -->|Playwright| cards["岗位卡片<br/><small>dict</small>"]
  cards -->|save_job| jdb[("jobs.db<br/><small>本机 SQLite</small>")]
  jdb -->|"push.py<br/>to_ingest()"| api["/api/ingest/jobs"]
  api -->|"isITRole 闸门<br/>归一化"| D1[("D1 · jobs<br/><small>436 行</small>")]
  D1 -->|"send-digest.js<br/>36 小时窗口"| pool["候选池"]
  pool -->|"匹配 + 排序 + 封顶"| mail["邮件<br/><small>Resend</small>"]
  mail --> member(("会员"))
  pool -.->|"没进这封信的"| snap[("digest_run_jobs<br/><small>1,556 行</small>")]
  mail --> sends[("job_sends<br/>digest_runs")]
  mail --> deliv[("job_deliveries<br/><small>2,982 行 · 防重复</small>")]
  snap --> portal["门户续页<br/>my-jobs"]
  sends --> portal
  member -.->|点击| clicks[("job_clicks")]
  member -.->|回信| conv[("conversations<br/>messages")]'''


# ── HTML ─────────────────────────────────────────────────────────────────────
def esc(s):
    return html.escape(str(s), quote=False)


def col_row(tt, c):
    marks = []
    if c['name'] in tt['pk']:
        marks.append('<span class="pill pk">PK</span>')
    fk = next((f for f in tt['fks'] if c['name'] in f['from']), None)
    if fk:
        marks.append(f'<span class="pill fk">→ {esc(fk["table"])}</span>')
    if c['unique']:
        marks.append('<span class="pill uk">UNIQUE</span>')
    if c['notNull']:
        marks.append('<span class="pill nn">NOT NULL</span>')
    if c['check']:
        chk = re.sub(r'\s+', ' ', c['check'])[:90]
        marks.append(f'<span class="pill ck" title="{esc(c["check"])}">CHECK {esc(chk)}</span>')
    if c['default'] is not None:
        marks.append(f'<span class="pill df">默认 {esc(c["default"])}</span>')
    return (f'<tr><td><code>{esc(c["name"])}</code></td>'
            f'<td class="ty">{esc(c["type"].lower())}</td>'
            f'<td>{" ".join(marks)}</td></tr>')


def build_html():
    P = []
    A = P.append
    # ⚠️ charset 必须有，而且必须在最前面。
    #
    # 第一版直接从 <title> 开始，没有 doctype 也没有 <meta charset>。
    # 用 http 服务器看是好的（服务器给了 Content-Type），而【双击打开本地文件】
    # 时 Chrome 只能猜编码 —— 一份全中文的文档整页变成 æ•°æ®åº“。
    # 又是那个形状：在我这里是绿的，在你那里是乱码，而且哪里都不报错。
    # pipeline.html 也犯了同一个错，2026-08-14 一起补的。
    #
    # The first version began at <title>: fine over http, mojibake on
    # double-click, where Chrome has only guessing to go on.
    A('<!doctype html>')
    A('<html lang="zh">')
    A('<head>')
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<meta name="color-scheme" content="light dark">')
    A('<title>FlowGT 数据库全景 · ERD / schema / ETL</title>')
    A('<style>')
    # 令牌从 tokens.css 读，不再从另一个 HTML 文件里抠 —— 见 tokens.css 顶部。
    A((HERE / 'tokens.css').read_text(encoding='utf-8'))
    A('''
  /* ── ERD 专用 ── */
  .mm{background:var(--card);border:1px solid var(--line);border-radius:13px;
      padding:16px;box-shadow:var(--shadow);overflow-x:auto}
  .mm pre.mermaid{margin:0;background:none;border:0}
  table.sch{width:100%;border-collapse:collapse;font-size:13.5px}
  table.sch th{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
      color:var(--muted);font-weight:800;padding:6px 8px;border-bottom:1px solid var(--line)}
  table.sch td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  table.sch tr:last-child td{border-bottom:0}
  td.ty{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
  .pill{display:inline-block;font:700 10.5px/1.5 var(--body);letter-spacing:.03em;
      padding:1px 7px;border-radius:999px;margin:1px 3px 1px 0;white-space:nowrap}
  .pk{background:var(--accent);color:#fff}
  .fk{background:var(--accent-bg);color:var(--accent)}
  .uk{background:var(--warn-bg);color:var(--warn)}
  .nn{background:var(--soft);color:var(--muted)}
  .ck{background:var(--soft);color:var(--ink-2);font-family:var(--mono);font-weight:500;
      max-width:100%;overflow:hidden;text-overflow:ellipsis}
  .df{background:var(--soft);color:var(--muted);font-family:var(--mono);font-weight:500}
  details.tbl{background:var(--card);border:1px solid var(--line);border-radius:11px;
      box-shadow:var(--shadow);overflow:hidden}
  details.tbl>summary{cursor:pointer;padding:12px 16px;list-style:none;display:flex;
      align-items:baseline;gap:10px;flex-wrap:wrap}
  details.tbl>summary::-webkit-details-marker{display:none}
  details.tbl>summary::before{content:"▸";color:var(--accent);font-weight:800;flex:none}
  details.tbl[open]>summary::before{content:"▾"}
  details.tbl>summary b{font-family:var(--mono);font-size:14px}
  details.tbl>summary .n{color:var(--muted);font-size:12.5px;margin-left:auto;
      font-variant-numeric:tabular-nums}
  details.tbl>div{padding:0 16px 14px}
  .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:11px;
      padding:13px 15px;box-shadow:var(--shadow)}
  .stat b{display:block;font-size:26px;line-height:1.1;font-variant-numeric:tabular-nums}
  .stat span{font-size:12px;color:var(--muted)}
  .prin{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
      border-radius:0 12px 12px 0;padding:15px 18px;box-shadow:var(--shadow)}
  .prin h3{margin-bottom:5px}
  .prin .src{font-family:var(--mono);font-size:11.5px;color:var(--accent);margin-bottom:8px}
  .prin p{font-size:14.5px;color:var(--ink-2)}
  .mig{font-family:var(--mono);font-size:12.5px;display:grid;
      grid-template-columns:auto 1fr;gap:4px 14px}
  .mig .id{color:var(--accent);white-space:nowrap}
  .mig .ti{color:var(--ink-2);overflow-wrap:anywhere}
''')
    A('</style>')
    A('</head>')
    A('<body>')

    A('<div class="wrap">')

    # 封面
    A('<section>')
    A('<div><div class="eyebrow">FlowGT · 数据库全景</div>')
    A('<h1>31 张表，6,074 行</h1></div>')
    A('<p class="lede">它们不是设计出来的，是 <b>2026-08-05 到 08-11 十天里长出来的</b> —— '
      '23 个迁移，其中 4 个是在修前一个迁移犯的错。这一页把真实的 schema、'
      '它们之间的关系、以及每一处「为什么这样建」摆在一起。</p>')
    A('<div class="grid2">')
    for b, s in [(f'{len(TABLES)}', '张表'), (f'{M["totalRows"]:,}', '行数据'),
                 (f'{sum(len(t["columns"]) for t in TABLES.values())}', '个字段'),
                 (f'{sum(len(t["fks"]) for t in TABLES.values())}', '个外键'),
                 (f'{sum(len(v) for v in INDEXES.values())}', '个索引'),
                 (f'{len(MIGRATIONS)}', '个迁移')]:
        A(f'<div class="stat"><b>{b}</b><span>{s}</span></div>')
    A('</div>')
    A('<div class="note">这一页由 <code>build_erd.py</code> 从生产库的 '
      '<code>sqlite_master</code> 直接生成 —— 也就是数据库<b>自己保存的建表语句</b>。'
      '手写的 schema 文档从写完那一刻就开始过期，而且它过期时不会报错。</div>')
    A('</section><hr>')

    # 设计原则
    A('<section>')
    A('<div><div class="eyebrow">怎么做的</div><h2>十条原则，每一条都有出处</h2></div>')
    A('<p class="lede">下面每一条后面都跟着一个真实的迁移文件名。'
      '「有出处」和「听起来对」是两件事 —— 后者是这个仓库最不需要的东西。</p>')
    for i, (title, src, body) in enumerate(PRINCIPLES, 1):
        A(f'<div class="prin"><h3>{i} · {esc(title)}</h3>'
          f'<div class="src">migrations/{esc(src)}.sql</div><p>{body}</p></div>')
    A('</section><hr>')

    # 全局图
    A('<section>')
    A('<div><div class="eyebrow">全局</div><h2>八个域，和它们之间的线</h2></div>')
    A('<p class="lede">32 张表画成一张字段级 ERD 没人看得懂 —— 那种图的作用是显得很厉害，'
      '不是让人明白。所以按<b>每张表服务的那件事</b>分域，先看域，再看域内。</p>')
    A(f'<div class="mm"><pre class="mermaid">{esc(overview_mermaid())}</pre></div>')
    A('</section><hr>')

    # ETL
    A('<section>')
    A('<div><div class="eyebrow">数据怎么流</div><h2>从一张网页，到一封邮件，再回到库里</h2></div>')
    A('<p class="lede">实线是数据进来的路，虚线是它出去之后留下的痕迹。'
      '这条链路的每一站在配套的 <code>etl.ipynb</code> 里都能自己跑一遍、'
      '把中间结果打印出来。</p>')
    A(f'<div class="mm"><pre class="mermaid">{esc(etl_mermaid())}</pre></div>')
    A('<div class="warn"><b>注意 <code>digest_run_jobs</code> 那条虚线。</b>'
      '它存的是「这封信当时<b>没</b>发给他的岗位」的快照 —— 会员点「查看剩余岗位」'
      '看到的就是它。刻意<b>不</b>对 <code>jobs</code> 建外键：'
      '岗位下架了，那封信当时的样子也不该跟着变。</div>')
    A('</section><hr>')

    # 每个域
    for d in DOMAINS:
        A('<section>')
        A(f'<div><div class="eyebrow">域 · {esc(d["key"])}</div>'
          f'<h2>{esc(d["title"])}</h2></div>')
        if d['blurb']:
            A(f'<p class="lede">{esc(d["blurb"])}</p>')
        A(f'<div class="mm"><pre class="mermaid">{esc(mermaid_for(d))}</pre></div>')
        for t in d['tables']:
            tt = TABLES[t]
            idx = INDEXES.get(t, [])
            A(f'<details class="tbl"><summary><b>{esc(t)}</b>'
              f'<span class="n">{len(tt["columns"])} 列 · {tt["rows"]:,} 行'
              f'{" · " + str(len(idx)) + " 个索引" if idx else ""}</span></summary><div>')
            A('<table class="sch"><thead><tr><th>字段</th><th>类型</th><th>约束</th></tr></thead><tbody>')
            for c in tt['columns']:
                A(col_row(tt, c))
            A('</tbody></table>')
            if len(tt['pk']) > 1:
                A(f'<p style="font-size:13px;color:var(--muted);margin-top:8px">'
                  f'复合主键：<code>({esc(", ".join(tt["pk"]))})</code></p>')
            if idx:
                A('<p style="font-size:13px;color:var(--muted);margin-top:8px">索引：'
                  + '　'.join(f'<code>{esc(i["name"])}</code>'
                             + ('<span class="pill uk">UNIQUE</span>' if i['unique'] else '')
                             for i in idx) + '</p>')
            A('</div></details>')
        A('</section><hr>')

    # 迁移历史
    A('<section>')
    A('<div><div class="eyebrow">设计记录</div><h2>23 个迁移，就是这个 schema 的思路</h2></div>')
    A('<p class="lede">迁移的<b>文件名说的是原因，不是改动</b>。'
      '看这一列名字就能读出十天里发生了什么 —— 包括做错的那几次，'
      '它们被记成错误，而不是悄悄改掉。</p>')
    A('<div class="mig">')
    for m in MIGRATIONS:
        A(f'<div class="id">{esc(m["id"].split("-")[0])}</div>'
          f'<div class="ti">{esc(m["title"])}</div>')
    A('</div>')
    A('<div class="note"><b>0016 → 0020 那一段值得看。</b>'
      '0015 改了套餐名，0016 补 0015 漏掉的约束，而 0016 重建表时'
      '把四个附件列压成了一列 —— 0020 又把它们还回去。'
      'SQLite 改不了 CHECK 约束，只能重建表，而重建表就是这么容易掉东西。</div>')
    A('</section>')

    A('</div>')
    A('</body></html>')
    A('''<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
mermaid.initialize({ startOnLoad: true, theme: dark ? 'dark' : 'default',
  er: { useMaxWidth: true }, flowchart: { useMaxWidth: true } });
</script>''')
    return '\n'.join(P)


if __name__ == '__main__':
    ARCH.mkdir(parents=True, exist_ok=True)
    out = ARCH / 'erd.html'
    out.write_text(build_html(), encoding='utf-8')
    print(f'  ✓ {out.name}  {out.stat().st_size:,} 字节')
    print(f'    {len(TABLES)} 张表 · {len(DOMAINS)} 个域 · {len(PRINCIPLES)} 条原则'
          f' · {len(MIGRATIONS)} 个迁移')
