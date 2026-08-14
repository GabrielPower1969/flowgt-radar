"""从真实 DDL 解析出一份结构化的 schema 模型。

    python3 schema_model.py --refresh    # 重新去生产库拉 DDL（要 wrangler 登录）
    python3 schema_model.py              # 用缓存的 DDL 重新解析

── 为什么解析 DDL 而不是手写一份 ─────────────────────────────────────────────

手写的 schema 文档从写完那一刻起就开始过期，而且【它过期时不会报错】。
这个仓库反复吃的亏就是这个形状：一份和事实不符的记录，读起来和事实一模一样。

所以这里只有一个事实源：`SELECT sql FROM sqlite_master`，也就是数据库
自己保存的建表语句。表加了列、约束改了、索引没了 —— 下一次跑这个脚本就会
反映出来，不需要任何人记得去改文档。

Parsed from the database's own DDL rather than written by hand: a hand-kept
schema doc starts going stale the moment it is written, and it does not raise
when it does — it just reads exactly like the truth.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SITE = HERE.parent / 'flowgt-website'
CACHE = HERE / 'schema-cache.json'


# ── 从生产库拿 DDL / pull the DDL ─────────────────────────────────────────────
def d1(sql):
    env = dict(os.environ, CI='1', WRANGLER_SEND_METRICS='false')
    p = subprocess.run(
        ['npx', 'wrangler', 'd1', 'execute', 'flowgt', '--remote', '--json', '--command', sql],
        cwd=SITE, env=env, capture_output=True, text=True)
    body = p.stdout or ''
    if '"error"' in body:
        note = ''
        try:
            err = json.JSONDecoder().raw_decode(body[body.index('{'):])[0]['error']
            note = (err.get('notes') or [{}])[0].get('text', '')
        except Exception:
            pass
        sys.exit(f'查库失败：{note or body[:300]}')
    out, _ = json.JSONDecoder().raw_decode(body[body.index('['):])
    return out[0]['results']


def refresh():
    print('  从生产库拉 DDL…')
    master = d1("SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE sql IS NOT NULL ORDER BY type, name;")
    tabs = sorted(r['name'] for r in master
                  if r['type'] == 'table' and not r['name'].startswith('_cf'))
    print(f'  {len(tabs)} 张表，数行数（D1 的 compound SELECT 上限很低，3 个一批）…')
    counts = {}
    for i in range(0, len(tabs), 3):
        chunk = tabs[i:i + 3]
        sql = ' UNION ALL '.join(f"SELECT '{t}' tbl, COUNT(*) n FROM {t}" for t in chunk) + ';'
        for r in d1(sql):
            counts[r['tbl']] = r['n']
    CACHE.write_text(json.dumps({'master': master, 'counts': counts},
                                ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'  → {CACHE.name}')


# ── 解析 / parse ──────────────────────────────────────────────────────────────
#
# 只用正则解析 SQLite 的 CREATE TABLE。这【不是】一个通用的 SQL 解析器，
# 它只需要认得这个仓库自己写出来的那种 DDL —— 而那些 DDL 是 migrations/
# 里手写的，风格一致。真要通用解析器，代价远大于收益。
# A regex reader for this repo's own DDL, not a general SQL parser. The DDL is
# hand-written in migrations/ in one consistent style; a real parser would cost
# far more than it returns here.

TYPES = r'(?:INTEGER|TEXT|REAL|BLOB|NUMERIC)'


def split_top_level(body):
    """按顶层逗号切开列定义 —— 括号里的逗号不算（CHECK (x IN ('a','b'))）。"""
    out, depth, cur = [], 0, ''
    for ch in body:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [s.strip() for s in out if s.strip()]


def parse_table(sql):
    m = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?(\w+)["`\]]?\s*\((.*)\)',
                  sql, re.S | re.I)
    if not m:
        return None
    name, body = m.group(1), m.group(2)
    cols, fks, checks, pks = [], [], [], []
    for part in split_top_level(body):
        up = part.upper()
        if up.startswith('FOREIGN KEY'):
            f = re.search(r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+["`\[]?(\w+)["`\]]?\s*\(([^)]+)\)',
                          part, re.I)
            if f:
                fks.append({'from': [c.strip().strip('"`[]') for c in f.group(1).split(',')],
                            'table': f.group(2),
                            'to': [c.strip().strip('"`[]') for c in f.group(3).split(',')],
                            'onDelete': 'CASCADE' if 'CASCADE' in up else
                                        ('SET NULL' if 'SET NULL' in up else None)})
            continue
        if up.startswith('PRIMARY KEY'):
            p = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', part, re.I)
            if p:
                pks = [c.strip().strip('"`[]') for c in p.group(1).split(',')]
            continue
        if up.startswith('UNIQUE') or up.startswith('CHECK') or up.startswith('CONSTRAINT'):
            if up.startswith('CHECK'):
                checks.append(part.strip())
            continue
        c = re.match(r'["`\[]?(\w+)["`\]]?\s+(' + TYPES + r')?', part, re.I)
        if not c:
            continue
        cname = c.group(1)
        col = {
            'name': cname,
            'type': (c.group(2) or '').upper() or 'TEXT',
            'notNull': 'NOT NULL' in up,
            'pk': 'PRIMARY KEY' in up,
            'unique': 'UNIQUE' in up,
            'default': (re.search(r'DEFAULT\s+([^\s,]+)', part, re.I).group(1)
                        if re.search(r'DEFAULT\s+', part, re.I) else None),
            'check': (re.search(r'CHECK\s*\((.*)\)', part, re.I | re.S).group(1).strip()
                      if 'CHECK' in up else None),
        }
        if col['pk']:
            pks.append(cname)
        # 列内联的 REFERENCES
        r = re.search(r'REFERENCES\s+["`\[]?(\w+)["`\]]?\s*(?:\(([^)]+)\))?', part, re.I)
        if r:
            fks.append({'from': [cname], 'table': r.group(1),
                        'to': [(r.group(2) or 'id').strip().strip('"`[]')],
                        'onDelete': 'CASCADE' if 'CASCADE' in up else
                                    ('SET NULL' if 'SET NULL' in up else None)})
        cols.append(col)
    return {'name': name, 'columns': cols, 'fks': fks, 'pk': pks, 'checks': checks}


# ── 分域 / domains ────────────────────────────────────────────────────────────
#
# 32 张表画成一张 ERD 没人看得懂 —— 那种图的作用是显得很厉害，不是让人明白。
# 按【它们服务的那件事】分域，每域单独一张图，域之间只画跨域的那几根线。
# One ERD of 32 tables impresses and explains nothing. Grouped by the job each
# table does, one diagram per domain, with only the crossing edges drawn between.
DOMAINS = [
    ('identity', '身份与权限 / identity & access',
     '谁是谁、他能看到什么、他做过什么。所有其它域都从这里挂出去。',
     ['employers', 'identities', 'sessions', 'login_codes', 'oauth_states', 'admin_audit']),
    ('market', '岗位事实 / job market facts',
     '抓回来的岗位本身，加上归一化的判断和每日汇总。为「一年后的趋势问题」建的。',
     ['jobs', 'job_daily', 'role_taxonomy', 'scrape_runs']),
    ('delivery', '推送 / delivery',
     '把岗位变成一封信，并且留下足够的痕迹回答「他到底收到了什么」。',
     ['job_subscriptions', 'job_sends', 'digest_runs', 'digest_run_jobs',
      'job_deliveries', 'job_clicks']),
    ('talk', '会话与请求 / conversations',
     '不是自动化队列，是「别忘事」：他三周前说过什么、我答应过什么。',
     ['conversations', 'messages', 'job_requests']),
    ('cv', 'CV 管线 / CV pipeline',
     '最私密的东西。静态加密，解密只有两条代码路径，每次下载留审计。',
     ['cv_documents', 'cv_reviews', 'cv_rubric']),
    ('broadcast', '群发 / broadcasts',
     '发之前必须先说清楚这是「服务信息」还是「商业信息」—— 法律地位完全不同。',
     ['broadcasts', 'broadcast_deliveries']),
    ('resources', '会员资源 / resources',
     '周报、AI 信息、播客。形状相同，所以一张表，不是三张。',
     ['resources', 'resource_events', 'resource_saves', 'resource_seen']),
    ('misc', '其它 / the rest', '',
     ['ai_blueprints', 'outcomes', 'usage_events', 'employer_profiles']),
]


def build():
    if not CACHE.exists():
        sys.exit(f'没有 {CACHE.name}，先跑 python3 {pathlib.Path(__file__).name} --refresh')
    raw = json.loads(CACHE.read_text(encoding='utf-8'))
    master, counts = raw['master'], raw['counts']

    tables = {}
    for r in master:
        if r['type'] != 'table' or r['name'].startswith('_cf'):
            continue
        t = parse_table(r['sql'] or '')
        if t:
            t['rows'] = counts.get(t['name'], 0)
            t['ddl'] = r['sql']
            tables[t['name']] = t

    indexes = {}
    for r in master:
        if r['type'] == 'index' and not r['name'].startswith('sqlite_'):
            indexes.setdefault(r['tbl_name'], []).append(
                {'name': r['name'], 'sql': r['sql'],
                 'unique': 'UNIQUE' in (r['sql'] or '').upper()})

    placed = set()
    domains = []
    for key, title, blurb, names in DOMAINS:
        got = [n for n in names if n in tables]
        placed.update(got)
        if got:
            domains.append({'key': key, 'title': title, 'blurb': blurb, 'tables': got})
    leftover = sorted(set(tables) - placed)
    if leftover:
        domains.append({'key': 'unplaced', 'title': '还没分域 / unplaced',
                        'blurb': '这一栏应该是空的。不空说明加了新表而没有归域 —— '
                                 '这个脚本会把它显出来，而不是默默漏掉。',
                        'tables': leftover})
    return {'tables': tables, 'indexes': indexes, 'domains': domains,
            'totalRows': sum(counts.values())}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()
    if a.refresh:
        refresh()
    m = build()
    print(f"\n  {len(m['tables'])} 张表 · {m['totalRows']:,} 行 · {len(m['domains'])} 个域\n")
    for d in m['domains']:
        rows = sum(m['tables'][t]['rows'] for t in d['tables'])
        cols = sum(len(m['tables'][t]['columns']) for t in d['tables'])
        fks = sum(len(m['tables'][t]['fks']) for t in d['tables'])
        print(f"  {d['title']}")
        print(f"     {len(d['tables'])} 张表 · {cols} 列 · {fks} 个外键 · {rows:,} 行")
        for t in d['tables']:
            tt = m['tables'][t]
            print(f"       {t:<24}{len(tt['columns']):>3} 列 {tt['rows']:>6} 行"
                  f"  {'外键 ' + str(len(tt['fks'])) if tt['fks'] else ''}")
        print()
