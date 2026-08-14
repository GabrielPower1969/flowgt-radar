"""把 HTML 里的 mermaid 源码在【生成时】渲染成内嵌 SVG。

    python3 render_mermaid.py erd.html

── 为什么不留着运行时加载 CDN ────────────────────────────────────────────────

第一版是 <script type="module">import mermaid from 'https://cdn…'</script>。
它有一个不会报错的失败：**双击打开本地文件时，Chrome 会因为 CORS 挡掉
file:// 下的 ES module 导入** —— 页面照常显示，只是十张图全变成一堆源码文本。
而写这一页的人（我）在 http 服务器上看是好的。

又是那个形状：在我这里是绿的，在你那里什么都没有，而且没有任何地方报错。

所以改成生成时渲染：build 的时候连一次网把图变成 SVG 内嵌进去，
之后这个文件**离线、双击、发邮件、当附件**都能看。运行时零依赖。

The first version imported mermaid from a CDN at runtime. That fails silently
when the file is opened directly: Chrome blocks ES module imports over file://
for CORS, so all ten diagrams degrade to source text — while looking fine to
whoever built it over http. Rendering at build time makes the page work offline,
by double-click, as an email attachment. No runtime dependency at all.
"""
import asyncio
import html
import pathlib
import re
import sys

MERMAID_CDN = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'

SHELL = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#fff;font-family:-apple-system,"PingFang SC",sans-serif}</style>
</head><body><div id="host"></div>
<script type="module">
import mermaid from '__CDN__';
// 只设字号。颜色不在这里猜 —— 见下面 CSS 那一段。
window.__render = async (src, theme) => {
  mermaid.initialize({ startOnLoad:false, theme, securityLevel:'loose',
                       er:{useMaxWidth:true}, flowchart:{useMaxWidth:true},
                       fontFamily:'-apple-system,"PingFang SC",sans-serif',
                       themeVariables: { fontSize:'14px' } });
  try {
    const { svg } = await mermaid.render('m' + Math.abs(src.length*7919 % 100000), src);
    return { ok:true, svg };
  } catch (e) { return { ok:false, err:String(e && e.message || e) }; }
};
window.__ready = true;
</script></body></html>""".replace('__CDN__', MERMAID_CDN)


async def render_all(sources):
    """回传 [(ok, svg_or_error), …]，浅色和深色各一份。"""
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        page = await b.new_page()
        await page.set_content(SHELL)
        await page.wait_for_function('window.__ready === true', timeout=30000)
        for i, src in enumerate(sources, 1):
            light = await page.evaluate('([s,t]) => window.__render(s,t)', [src, 'default'])
            dark = await page.evaluate('([s,t]) => window.__render(s,t)', [src, 'dark'])
            if not light.get('ok'):
                print(f'  ✗ 第 {i} 张图渲染失败：{light.get("err","")[:160]}')
                out.append((False, light.get('err', '')))
                continue
            print(f'  ✓ 第 {i} 张图  浅色 {len(light["svg"]):>7,} 字 · '
                  f'深色 {len(dark["svg"]) if dark.get("ok") else 0:>7,} 字')
            out.append((True, {'light': light['svg'],
                               'dark': dark['svg'] if dark.get('ok') else light['svg']}))
        await b.close()
    return out


def main(path):
    p = pathlib.Path(path)
    doc = p.read_text(encoding='utf-8')
    blocks = re.findall(r'<pre class="mermaid">(.*?)</pre>', doc, re.S)
    if not blocks:
        sys.exit('  没有找到 mermaid 块')
    print(f'  {len(blocks)} 张图，开始渲染…')
    srcs = [html.unescape(b) for b in blocks]
    rendered = asyncio.run(render_all(srcs))

    bad = [i for i, (ok, _) in enumerate(rendered, 1) if not ok]
    if bad:
        sys.exit(f'\n  ✗ 第 {bad} 张图渲染失败 —— 不写回文件。\n'
                 f'    半渲染的页面比没渲染更糟：有的图有，有的图是源码，\n'
                 f'    而看的人会以为那几张就是这样。')

    it = iter(rendered)

    def sub(_m):
        ok, svgs = next(it)
        # 两份 SVG，靠 CSS 切换 —— mermaid 的深色主题是它自己算的配色，
        # 用 filter:invert 之类的把浅色图硬转深色会毁掉语义颜色。
        return (f'<div class="mmfig">'
                f'<div class="mm-light">{svgs["light"]}</div>'
                f'<div class="mm-dark">{svgs["dark"]}</div>'
                f'</div>')

    doc = re.sub(r'<pre class="mermaid">.*?</pre>', sub, doc, flags=re.S)
    # 运行时不再需要 mermaid
    doc = re.sub(r'<script type="module">\s*import mermaid.*?</script>', '', doc, flags=re.S)
    doc = doc.replace('</style>', '''
  .mmfig svg{max-width:100%;height:auto;display:block;margin:0 auto}
  /* ⚠️ 文字颜色在这里定，不在 mermaid 的 themeVariables 里定。
     试过那条路：mermaid 11 的 ER 渲染器用的变量名和文档对不上，
     设了 primaryTextColor/textColor 之后表名变成白底白字 —— 比原来更看不清。
     SVG 是内嵌在这一页里的，我控制得了它的 CSS，那就用确定的办法。
     一张看不清的图比没有图更糟：它占了位置，还让人以为这里已经解释过了。
     Colour is set here, not through mermaid's themeVariables: mermaid 11's ER
     renderer does not use the variable names the docs suggest, and setting them
     produced white-on-white. The SVG is inlined in this page, so control it here. */
  /* mermaid 11 把标签渲染成 foreignObject 里的 HTML，【不是】 SVG <text>。
     实测：这张图里 0 个 <text>、156 个 foreignObject，
     里面 div 的计算颜色是 rgb(204,204,204) —— 浅灰，所以看不清。
     选择器写 `svg text` 一个都选不中，改完等于没改。
     mermaid 11 renders labels as HTML inside foreignObject, not SVG <text>:
     measured 0 text nodes and 156 foreignObjects here, their divs computing to
     #ccc. A `svg text` rule matches nothing and changes nothing. */
  .mmfig svg text{fill:var(--ink)!important;font-family:var(--body)!important}
  .mmfig svg foreignObject div,
  .mmfig svg foreignObject p,
  .mmfig svg foreignObject span{
      color:var(--ink)!important;font-family:var(--body)!important}
  .mmfig svg foreignObject small{color:var(--muted)!important}
  .mmfig svg .er.entityLabel{fill:var(--ink)!important;font-weight:700}
  .mmfig svg .er.attributeBoxOdd{fill:var(--card)!important;stroke:var(--line)!important}
  .mmfig svg .er.attributeBoxEven{fill:var(--soft)!important;stroke:var(--line)!important}
  .mmfig svg .er.entityBox{fill:var(--accent-bg)!important;stroke:var(--accent)!important}
  .mmfig svg .er.relationshipLine{stroke:var(--accent)!important}
  .mmfig svg .er.relationshipLabelBox{fill:var(--bg)!important;opacity:.92}
  .mmfig svg .node rect,.mmfig svg .node polygon,.mmfig svg .node circle{
      fill:var(--card)!important;stroke:var(--line)!important}
  .mmfig svg .cluster rect{fill:var(--soft)!important;stroke:var(--line)!important}
  .mmfig svg .edgePath path,.mmfig svg .flowchart-link{stroke:var(--accent)!important}
  .mmfig svg marker path{fill:var(--accent)!important;stroke:var(--accent)!important}
  .mm-dark{display:none}
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]) .mm-light{display:none}
    :root:not([data-theme="light"]) .mm-dark{display:block}}
  :root[data-theme="dark"] .mm-light{display:none}
  :root[data-theme="dark"] .mm-dark{display:block}
  :root[data-theme="light"] .mm-light{display:block}
  :root[data-theme="light"] .mm-dark{display:none}
</style>''', 1)
    p.write_text(doc, encoding='utf-8')
    print(f'\n  ✓ {p.name} 已内嵌 {len(blocks)} 张 SVG，{p.stat().st_size:,} 字节')
    print('    运行时零依赖：离线、双击、当附件都能看。')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'erd.html')
