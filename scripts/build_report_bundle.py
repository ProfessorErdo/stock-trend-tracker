#!/usr/bin/env python3
"""Build a self-contained HTML bundle of the five grid_v1 reports, plus PDF."""
import base64, html, mimetypes, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
OUT_DIR = DOCS / 'pdf'
OUT_DIR.mkdir(parents=True, exist_ok=True)
HTML_PATH = OUT_DIR / 'grid-v1-reports-2026-11.html'
PDF_PATH = OUT_DIR / 'grid-v1-reports-2026-11.pdf'

REPORTS = [
    ('summary', '00', '2×2 汇总', 'grid-v1-summary-2026-11.md'),
    ('1052-nodiv', '01', '1052 × 非股息', 'grid-v1-1052-nodiv-2026-11.md'),
    ('1052-div', '02', '1052 × 股息', 'grid-v1-1052-div-2026-11.md'),
    ('932-nodiv', '03', '932 × 非股息', 'grid-v1-932-nodiv-2026-11.md'),
    ('932-div', '04', '932 × 股息', 'grid-v1-932-div-2026-11.md'),
]
MD_ANCHORS = {f: f'#report-{rid}' for rid, _, _, f in REPORTS}

def pandoc_fragment(path: Path) -> str:
    cmd = ['pandoc', '-f', 'markdown', '-t', 'html5', '--wrap=none', str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'pandoc failed for {path}: {r.stderr[:500]}')
    return r.stdout

def embed_images(frag: str) -> str:
    def repl(m):
        src = html.unescape(m.group(1))
        if src.startswith(('data:', 'http://', 'https://')):
            return m.group(0)
        p = (DOCS / src).resolve()
        if not p.exists():
            print(f'WARN image missing: {src}', file=sys.stderr)
            return m.group(0)
        mime = mimetypes.guess_type(str(p))[0] or 'image/png'
        b64 = base64.b64encode(p.read_bytes()).decode('ascii')
        return f'src="data:{mime};base64,{b64}"'
    return re.sub(r'src="([^"]+)"', repl, frag)

def rewrite_links(frag: str) -> str:
    for md, anchor in MD_ANCHORS.items():
        frag = frag.replace(f'href="{md}"', f'href="{anchor}"')
        frag = frag.replace(f'href="./{md}"', f'href="{anchor}"')
        frag = frag.replace(f'href="{md}#', f'href="{anchor}#')
    return frag

def build_fragment(rel: str) -> str:
    path = DOCS / rel
    frag = pandoc_fragment(path)
    frag = embed_images(frag)
    frag = rewrite_links(frag)
    return frag

CSS = r'''
:root{
  --ink:#17202a; --muted:#667085; --line:#e4e7ec; --accent:#0f766e;
  --bg:#f6f8fa; --panel:#ffffff; --soft:#f1f5f9; --warm:#b45309;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"STHeiti","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
  font-size:16px; line-height:1.7; -webkit-print-color-adjust:exact; print-color-adjust:exact;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
.app{display:flex; min-height:100vh}
.sidebar{
  width:286px; flex:0 0 286px; position:fixed; inset:0 auto 0 0; z-index:30;
  background:linear-gradient(180deg,#0b3b36 0%,#0f4f47 100%); color:#e6fffa;
  padding:30px 22px; overflow-y:auto;
}
.sidebar .brand{font-size:13px; letter-spacing:.12em; text-transform:uppercase; color:#99f6e4; margin-bottom:8px}
.sidebar h1{font-size:23px; line-height:1.3; margin:0 0 6px; color:#fff}
.sidebar .sub{font-size:13px; color:#b2f5ea; line-height:1.6; margin-bottom:22px}
.sidebar .meta{font-size:12px; color:#99f6e4; border-top:1px solid rgba(255,255,255,.16); padding-top:14px; margin-bottom:18px}
.toc{display:flex; flex-direction:column; gap:4px}
.toc a{
  color:#d7fffa; padding:9px 10px; border-radius:8px; font-size:14px;
  display:flex; gap:10px; align-items:baseline; line-height:1.35;
}
.toc a .no{font-size:11px; color:#5eead4; min-width:22px; font-variant-numeric:tabular-nums}
.toc a:hover,.toc a.active{background:rgba(255,255,255,.12); text-decoration:none}
.toc a.active{box-shadow:inset 3px 0 0 #5eead4}
.sidebar .hint{font-size:11px; color:#99f6e4; margin-top:22px; line-height:1.6}
.content{
  margin-left:286px; width:calc(100% - 286px); max-width:1180px;
  padding:34px 46px 90px;
}
.toolbar{
  position:fixed; top:18px; right:22px; z-index:40; display:flex; gap:8px;
}
.btn{
  border:1px solid rgba(15,118,110,.25); background:#fff; color:#0f4f47;
  border-radius:999px; padding:9px 15px; font-size:13px; cursor:pointer;
  box-shadow:0 6px 18px rgba(15,23,42,.08); font-family:inherit;
}
.btn:hover{background:#ecfdf5}
.btn.primary{background:var(--accent); color:#fff; border-color:var(--accent)}
.btn.primary:hover{background:#0d5f59}
.mobile-toggle{display:none}
.cover{
  background:linear-gradient(135deg,#0b3b36 0%,#115e56 60%,#0f766e 100%);
  color:#fff; border-radius:22px; padding:56px 52px 46px; margin-bottom:30px;
  box-shadow:0 22px 60px rgba(15,23,42,.16); position:relative; overflow:hidden;
}
.cover:after{
  content:""; position:absolute; width:420px; height:420px; border-radius:50%;
  right:-140px; top:-160px; background:radial-gradient(circle,rgba(94,234,212,.32),transparent 65%);
}
.cover .eyebrow{font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:#99f6e4; margin-bottom:14px}
.cover h1{font-size:44px; line-height:1.15; margin:0 0 12px; color:#fff; letter-spacing:-.02em}
.cover .subtitle{font-size:19px; color:#ccfbf1; margin:0 0 28px}
.cover .meta{font-size:13px; color:#b2f5ea; display:flex; flex-wrap:wrap; gap:8px 18px}
.cover .kpis{display:flex; flex-wrap:wrap; gap:12px; margin-top:30px; position:relative; z-index:1}
.kpi{background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.18); border-radius:12px; padding:12px 16px; min-width:150px}
.kpi b{display:block; font-size:22px; color:#fff; line-height:1.2}
.kpi span{font-size:11px; color:#b2f5ea}
.notice{
  background:#fffbeb; border:1px solid #fde68a; color:#78350f; border-radius:12px;
  padding:14px 18px; font-size:13px; line-height:1.65; margin:0 0 26px;
}
.report{
  background:var(--panel); border:1px solid var(--line); border-radius:18px;
  padding:30px 38px 34px; margin:0 0 28px; box-shadow:0 10px 30px rgba(15,23,42,.05);
  scroll-margin-top:20px;
}
.report-head{display:flex; align-items:center; gap:12px; margin-bottom:10px}
.report-no{
  font-size:12px; font-weight:700; color:#0f766e; background:#ccfbf1;
  border-radius:999px; padding:4px 10px; letter-spacing:.08em;
}
.report-title{font-size:13px; color:var(--muted); letter-spacing:.04em}
.report h1{font-size:28px; line-height:1.3; margin:6px 0 18px; letter-spacing:-.01em}
.report h2{font-size:21px; margin:30px 0 12px; padding-top:8px; border-top:1px solid var(--line)}
.report h3{font-size:17px; margin:22px 0 8px}
.report p{margin:10px 0}
.report blockquote{
  margin:14px 0; padding:12px 16px; background:#f0fdfa; border-left:4px solid #14b8a6;
  border-radius:0 10px 10px 0; color:#134e4a; font-size:14px;
}
.report ul,.report ol{padding-left:24px; margin:10px 0}
.report li{margin:5px 0}
.report table{
  width:100%; border-collapse:collapse; margin:14px 0 18px; font-size:13.5px;
  line-height:1.55; background:#fff;
}
.report th,.report td{border:1px solid var(--line); padding:7px 9px; vertical-align:top}
.report th{background:var(--soft); color:#0f172a; font-weight:700; text-align:left}
.report tr:nth-child(even) td{background:#fcfcfd}
.report code{background:#f1f5f9; border:1px solid #e2e8f0; border-radius:5px; padding:1px 5px; font-size:.9em}
.report pre{background:#0f172a; color:#e2e8f0; border-radius:10px; padding:14px 16px; overflow-x:auto; font-size:12.5px; line-height:1.55}
.report pre code{background:transparent; border:0; color:inherit; padding:0}
.report img{
  max-width:100%; height:auto; display:block; margin:16px auto 10px;
  border:1px solid var(--line); border-radius:10px; background:#fff;
}
.report figure{margin:18px 0}
.report figcaption{font-size:12px; color:var(--muted); text-align:center; margin-top:6px}
.source{font-size:11.5px; color:var(--muted); border-top:1px dashed var(--line); padding-top:10px; margin-top:24px}
.backtop{
  position:fixed; right:22px; bottom:22px; z-index:40; width:42px; height:42px;
  border-radius:50%; border:1px solid var(--line); background:#fff; color:#0f766e;
  font-size:18px; cursor:pointer; box-shadow:0 6px 18px rgba(15,23,42,.12); display:none;
}
.backtop.show{display:block}
@media (max-width: 980px){
  .sidebar{transform:translateX(-100%); transition:transform .2s ease; width:280px; flex-basis:280px}
  .sidebar.open{transform:translateX(0)}
  .content{margin-left:0; width:100%; padding:24px 18px 80px}
  .mobile-toggle{display:inline-flex}
  .toolbar{top:12px; right:12px}
  .cover{padding:38px 26px 34px; border-radius:16px}
  .cover h1{font-size:32px}
  .report{padding:22px 18px 26px; border-radius:14px}
  .report h1{font-size:23px}
  .report h2{font-size:19px}
  .report table{font-size:12px}
}
@media print{
  @page{size:A4; margin:14mm 12mm}
  body{background:#fff; font-size:10.5pt; line-height:1.55}
  .sidebar,.toolbar,.backtop,.mobile-toggle{display:none!important}
  .content{margin:0; width:100%; max-width:none; padding:0}
  .cover{page-break-after:always; border-radius:0; box-shadow:none; padding:0 0 18mm; background:#fff; color:#111}
  .cover:after{display:none}
  .cover .eyebrow,.cover .subtitle,.cover .meta,.cover .kpi span{color:#475569}
  .cover h1,.cover .kpi b{color:#111}
  .cover .kpi{background:#f1f5f9; border-color:#e2e8f0}
  .report{page-break-before:always; border:0; box-shadow:none; padding:0; margin:0; border-radius:0}
  .report:first-of-type{page-break-before:auto}
  .report h1{font-size:20pt}
  .report h2{font-size:14pt; border-top:1px solid #cbd5e1}
  .report h3{font-size:12pt}
  .report table{font-size:8.2pt; page-break-inside:auto}
  .report tr{page-break-inside:avoid}
  .report img{max-height:150mm; width:auto; max-width:100%; page-break-inside:avoid}
  .report blockquote{background:#f8fafc; border-left:3px solid #14b8a6}
  a{color:#111; text-decoration:none}
  .source{font-size:8pt}
}
'''

JS = r'''
(function(){
  const sidebar=document.querySelector('.sidebar');
  const toggle=document.querySelector('.mobile-toggle');
  if(toggle){toggle.addEventListener('click',()=>sidebar.classList.toggle('open'));}
  const links=[...document.querySelectorAll('.toc a')];
  const sections=links.map(a=>document.querySelector(a.getAttribute('href'))).filter(Boolean);
  const obs=new IntersectionObserver(entries=>{
    entries.forEach(e=>{
      if(e.isIntersecting){
        links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+e.target.id));
      }
    });
  },{rootMargin:'-15% 0px -70% 0px',threshold:0});
  sections.forEach(s=>obs.observe(s));
  const back=document.querySelector('.backtop');
  window.addEventListener('scroll',()=>{if(back) back.classList.toggle('show',window.scrollY>600);});
  if(back){back.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));}
  const printBtn=document.querySelector('#printBtn');
  if(printBtn){printBtn.addEventListener('click',()=>window.print());}
})();
'''

def build_html() -> str:
    toc = '\n'.join(
        f'<a href="#report-{rid}"><span class="no">{no}</span><span>{html.escape(title)}</span></a>'
        for rid, no, title, _ in REPORTS
    )
    sections = []
    for rid, no, title, rel in REPORTS:
        frag = build_fragment(rel)
        sections.append(f'''
<section class="report" id="report-{rid}">
  <div class="report-head"><span class="report-no">报告 {no}</span><span class="report-title">{html.escape(title)}</span></div>
  {frag}
  <p class="source">源文件：<a href="../{rel}">{rel}</a></p>
</section>''')
    body = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>grid_v1 · 2×2 回测报告（2026-11）</title>
<style>{CSS}</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">A-share · grid_v1</div>
    <h1>2×2 回测报告</h1>
    <div class="sub">1052 / 932 × 股息 / 非股息</div>
    <div class="meta">数据截止 2026-11-06<br>生成 2026-11-21 · 5 份报告</div>
    <nav class="toc">{toc}</nav>
    <div class="hint">屏幕阅读建议用左侧目录；打印或“另存为 PDF”会自动隐藏导航，按 A4 排版。</div>
  </aside>
  <main class="content">
    <div class="toolbar">
      <button class="btn mobile-toggle" type="button">目录</button>
      <button class="btn" type="button" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">顶部</button>
      <button class="btn primary" id="printBtn" type="button">打印 / 存为 PDF</button>
    </div>
    <section class="cover">
      <div class="eyebrow">grid_v1 · 2026-11</div>
      <h1>2×2 回测报告</h1>
      <div class="subtitle">1052 / 932 × 股息 / 非股息 · 五份报告合订</div>
      <div class="meta"><span>主指标 M3b</span><span>首买 2015-05</span><span>数据截止 2026-11-06</span><span>生成 2026-11-21</span></div>
      <div class="kpis">
        <div class="kpi"><b>138</b><span>股息 distinct / 池</span></div>
        <div class="kpi"><b>87</b><span>非股息 distinct / 池</span></div>
        <div class="kpi"><b>450</b><span>两池 distinct 合计</span></div>
        <div class="kpi"><b>15.53%</b><span>1052 股息推荐 M3b</span></div>
      </div>
    </section>
    <div class="notice"><b>阅读提示：</b>本合订本包含 1 份汇总 + 4 份子报告。股息格默认 ROE65；ROE55 是边界值，报告里单列。剔除 2021 / 剔除自身最高年两项稳健性检验<strong>只针对股息模式</strong>。</div>
    {''.join(sections)}
  </main>
</div>
<button class="backtop" type="button" title="回到顶部">↑</button>
<script>{JS}</script>
</body>
</html>'''
    return body

def make_pdf() -> bool:
    chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if not Path(chrome).exists():
        print('Chrome not found; HTML only', file=sys.stderr)
        return False
    cmd = [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
           '--disable-dev-shm-usage', '--user-data-dir=/tmp/chrome-headless-pdf',
           '--no-pdf-header-footer', '--run-all-compositor-stages-before-draw',
           '--virtual-time-budget=8000', f'--print-to-pdf={PDF_PATH}',
           f'file://{HTML_PATH}']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not PDF_PATH.exists():
        print(f'Chrome PDF failed: {r.returncode} {r.stderr[-500:]}', file=sys.stderr)
        return False
    return True

def main():
    html_text = build_html()
    HTML_PATH.write_text(html_text, encoding='utf-8')
    print(f'HTML: {HTML_PATH} ({HTML_PATH.stat().st_size/1024/1024:.1f} MB)')
    if make_pdf():
        print(f'PDF:  {PDF_PATH} ({PDF_PATH.stat().st_size/1024/1024:.1f} MB)')
    else:
        print('PDF not generated; open HTML and print to PDF manually.')

if __name__ == '__main__':
    main()
