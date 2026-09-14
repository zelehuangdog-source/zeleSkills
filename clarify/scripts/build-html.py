#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clarify 渲染脚本：把需求澄清 md 渲染为单文件自包含的 HTML。

本文件是 clarify 自带的一份副本，刻意不依赖 zele-plan —— 两个工具各持一份，
重复维护换取「单独拿出来就能用」。

图表管线：
  1. 先用 plantuml.jar 把 <md 同级>/diagrams/*.puml 渲染成同名 .svg
  2. 把 md 里的 ![[diagrams/xxx.svg]] 替换成内联 SVG

plantuml.jar 有 21MB，不纳入版本控制；缺失时脚本会自动从 Maven Central
下载一次（需要网络，之后就本地缓存了）。渲染产物 HTML 本身完全离线。

其他特性：
- 侧边目录：从 h2/h3 自动生成，支持点击跳转 + 滚动高亮
- 剥离 frontmatter 与 "## 目录" 段（HTML 有自己的侧边栏）
- Obsidian 双链 [[笔记]] 渲染成带标识的引用样式，不假装是链接
- HTML 完全离线可看，不依赖 CDN

用法：
    python3 build-html.py 澄清.md              # 输出同目录同名 .html
    python3 build-html.py 澄清.md -o out.html
    python3 build-html.py 澄清.md --open
    python3 build-html.py 澄清.md --no-render  # 跳过 puml 渲染，直接用已有 svg

退出码：0 成功，非 0 失败。
"""

import argparse
import base64
import glob
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ASSETS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets")
)

# plantuml.jar 有 21MB，不入库；首次运行时从这里拉一次
PLANTUML_URL = (
    "https://repo1.maven.org/maven2/net/sourceforge/plantuml/plantuml/"
    "1.2024.8/plantuml-1.2024.8.jar"
)

TOC_HEADING_RE = re.compile(r"^##\s*目\s*录\s*$", re.M)
NEXT_H2_RE = re.compile(r"^##\s+", re.M)
# md 中的图片式嵌入：![[diagrams/用例图.svg]] / ![[diagrams/用例图.svg|600]]
EMBED_SVG_RE = re.compile(r"!\[\[([^\]|]+\.svg)(?:\|[^\]]*)?\]\]", re.I)


def read_asset(name):
    """读取 assets 下的静态资源，缺失时给出可操作的报错。"""
    path = os.path.normpath(os.path.join(ASSETS_DIR, name))
    if not os.path.isfile(path):
        sys.exit("缺少资源文件：%s\n请重新获取该文件后重试。" % path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # 内联进 <script> 时，源码里的 </script 会提前闭合标签
    return content.replace("</script", "<\\/script")


# --------------------------------------------------------------------------
# PlantUML 渲染
# --------------------------------------------------------------------------

def ensure_plantuml_jar():
    """确保 plantuml.jar 就位，缺失时自动下载。返回 jar 路径或 None。

    jar 有 21MB，不纳入版本控制（仓库里的 .gitignore 会忽略 assets/*.jar）。
    首次运行时从 Maven Central 拉一次，之后走本地缓存，不再联网。
    """
    jar = os.path.normpath(os.path.join(ASSETS_DIR, "plantuml.jar"))
    if os.path.isfile(jar):
        return jar

    print("   · 首次运行：正在下载 plantuml.jar（约 21MB，仅此一次）...")
    try:
        os.makedirs(os.path.dirname(jar), exist_ok=True)
        with urllib.request.urlopen(PLANTUML_URL, timeout=180) as resp, open(jar, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as exc:  # 网络不通、超时、磁盘满等
        # 半截文件会让下次误判为"已存在"，必须清掉
        if os.path.isfile(jar):
            os.remove(jar)
        return None

    print("   · plantuml.jar 已就位（%s）" % jar)
    return jar


def render_plantuml(diagrams_dir):
    """把 diagrams/ 下所有 .puml 渲染成同名 .svg。返回 (成功数, 提示信息)。

    一次 java 调用批量渲染，避免每张图起一次 JVM。无 graphviz 时依赖
    PlantUML 内置的 Smetana 布局（.puml 里写 !pragma layout smetana 即可）。
    """
    pumls = sorted(glob.glob(os.path.join(diagrams_dir, "*.puml")))
    if not pumls:
        return 0, "diagrams/ 下没有 .puml，跳过渲染"

    jar = ensure_plantuml_jar()
    if not jar:
        return 0, "plantuml.jar 下载失败，跳过渲染，将使用已有 svg（检查网络后重跑）"

    java = os.environ.get("JAVA_HOME", "")
    java_bin = os.path.join(java, "bin", "java") if java else "java"
    if not os.path.isfile(java_bin) and shutil.which("java"):
        java_bin = "java"

    cmd = [java_bin, "-jar", jar, "-tsvg", "-charset", "UTF-8"] + pumls
    proc = subprocess.run(cmd, capture_output=True, text=True)

    made = sum(1 for p in pumls if os.path.isfile(os.path.splitext(p)[0] + ".svg"))
    if proc.returncode != 0:
        return made, "PlantUML 渲染有问题（退出码 %d）：%s" % (
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip()[:400],
        )
    return made, "已渲染 %d 张 PlantUML 图" % made


def clean_svg(svg):
    """把 PlantUML 产出的 SVG 改成可响应式缩放。

    原始 SVG 带固定 px 宽高和 preserveAspectRatio="none"，直接内联进页面后
    既不能自适应容器宽度，缩放还会被拉变形。这里剥掉尺寸、改成等比缩放。
    """
    m = re.match(r"(<svg[^>]*>)(.*)", svg, re.S)
    if not m:
        return svg
    tag, rest = m.group(1), m.group(2)
    # 只清理根标签上的 width/height/style，不能碰内部 <rect width="..."> 等
    tag = re.sub(r'\s(?:width|height)="[^"]*"', "", tag)
    tag = re.sub(r'\sstyle="[^"]*"', "", tag)
    tag = tag.replace('preserveAspectRatio="none"', 'preserveAspectRatio="xMidYMid meet"')
    if "preserveAspectRatio" not in tag and "viewBox" in tag:
        tag = tag.replace("<svg", '<svg preserveAspectRatio="xMidYMid meet"', 1)

    # 只给 viewBox 不够：没有 width 的 SVG 会撑满容器，小图（如 ER 图）会被
    # 放大到文字失真。用原始宽度封顶，大图仍能缩到容器内。
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', tag)
    if vb:
        natural = int(float(vb.group(1))) + 1
        tag = tag.replace(
            "<svg", '<svg style="max-width:%dpx;width:100%%;height:auto"' % natural, 1
        )

    tag = tag.replace("<svg", '<svg class="diagram-svg"', 1)
    return tag + rest


def inline_diagrams(md, base_dir):
    """把 md 里的 ![[xxx.svg]] 替换成内联 SVG，返回 (新 md, 缺失清单)。"""
    missing = []

    def repl(m):
        rel = m.group(1).strip()
        candidates = [
            os.path.join(base_dir, rel),
            os.path.join(base_dir, "diagrams", os.path.basename(rel)),
        ]
        for path in candidates:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    svg = clean_svg(f.read())
                name = os.path.splitext(os.path.basename(path))[0]
                return '\n<div class="diagram" data-name="%s">%s</div>\n' % (name, svg)
        missing.append(rel)
        return '\n<div class="diagram-missing">图未找到：%s（请确认 diagrams/%s.puml 已渲染）</div>\n' % (
            rel,
            os.path.splitext(os.path.basename(rel))[0],
        )

    return EMBED_SVG_RE.sub(repl, md), missing


# --------------------------------------------------------------------------
# markdown 预处理
# --------------------------------------------------------------------------

def split_frontmatter(md):
    """拆出 YAML frontmatter 与正文，返回 (frontmatter 或 None, 正文)。"""
    fm = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*\n?", md, re.S)
    if not fm:
        return None, md
    return fm.group(1), md[fm.end():]


def extract_title(frontmatter, md, fallback):
    """取文档标题：优先 frontmatter 的 title，其次首个一级标题。"""
    if frontmatter:
        hit = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", frontmatter, re.M)
        if hit:
            return hit.group(1).strip()
    hit = re.search(r"^#\s+(.+?)\s*$", md, re.M)
    return hit.group(1).strip() if hit else fallback


def strip_toc_section(md):
    """剥掉 md 里的「## 目录」整段（HTML 侧边栏会重新生成）。"""
    m = TOC_HEADING_RE.search(md)
    if not m:
        return md
    tail = md[m.end():]
    nxt = NEXT_H2_RE.search(tail)
    return md[: m.start()] + (tail[nxt.start():] if nxt else "")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f6f6f4; --card:#ffffff; --text:#24292f; --muted:#6b7280;
  --accent:#2f6f8f; --accent-soft:#eaf2f6; --border:#e4e6ea;
  --code-bg:#f4f5f7; --table-head:#f3f6f8; --sidebar:#1f2933; --sidebar-text:#c6ced6;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  background:var(--bg); color:var(--text); line-height:1.75; font-size:15px;
  -webkit-font-smoothing:antialiased;
}
/* ---------- 布局 ---------- */
#layout{display:flex; min-height:100vh}
#toc{
  width:290px; flex:0 0 290px; background:var(--sidebar); color:var(--sidebar-text);
  position:sticky; top:0; height:100vh; overflow-y:auto; padding:28px 0 60px;
}
#toc .toc-title{
  font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:#7d8b99; padding:0 24px 14px; font-weight:600;
}
#toc a{
  display:block; color:var(--sidebar-text); text-decoration:none;
  padding:7px 24px; font-size:13.5px; line-height:1.5;
  border-left:3px solid transparent; transition:background .12s,color .12s;
}
#toc a:hover{background:#2b3742; color:#fff}
#toc a.lv3{padding-left:42px; font-size:12.5px; color:#9aa7b4}
#toc a.active{border-left-color:var(--accent); background:#2b3742; color:#fff; font-weight:600}
#toc::-webkit-scrollbar{width:8px}
#toc::-webkit-scrollbar-thumb{background:#3b4753; border-radius:4px}
#main{flex:1; min-width:0; padding:56px 64px 120px; max-width:1020px; margin:0 auto}
/* ---------- 正文 ---------- */
#content h1{
  font-size:1.95em; line-height:1.35; margin:0 0 8px; padding-bottom:20px;
  border-bottom:2px solid var(--border); font-weight:700; letter-spacing:-.01em;
}
#content h2{
  font-size:1.4em; margin:52px 0 16px; padding-top:14px; font-weight:700;
  border-top:1px solid var(--border); scroll-margin-top:24px;
}
#content h3{font-size:1.12em; margin:32px 0 12px; font-weight:650; scroll-margin-top:24px}
#content h4{font-size:1em; margin:24px 0 10px; font-weight:650; color:#3d4753; scroll-margin-top:24px}
#content p{margin:14px 0}
#content ul,#content ol{margin:14px 0 14px 26px}
#content li{margin:6px 0}
#content li>ul,#content li>ol{margin:6px 0 6px 22px}
#content a{color:var(--accent); text-decoration:none; border-bottom:1px solid #bcd4e0}
#content a:hover{border-bottom-color:var(--accent)}
#content strong{font-weight:650}
#content hr{border:0; border-top:1px solid var(--border); margin:40px 0}
#content blockquote{
  margin:18px 0; padding:12px 20px; background:var(--accent-soft);
  border-left:3px solid var(--accent); border-radius:0 6px 6px 0; color:#37474f;
}
#content blockquote p{margin:6px 0}
#content code{
  background:var(--code-bg); padding:2px 6px; border-radius:4px;
  font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  font-size:.88em; color:#b4315b;
}
#content pre{
  background:var(--code-bg); padding:16px 18px; border-radius:8px;
  overflow-x:auto; margin:18px 0; border:1px solid var(--border);
}
#content pre code{background:none; padding:0; color:#24292f; font-size:12.8px; line-height:1.65}
#content table{border-collapse:collapse; width:100%; margin:20px 0; font-size:13.6px; display:block; overflow-x:auto}
#content th,#content td{border:1px solid var(--border); padding:9px 13px; text-align:left; vertical-align:top}
#content th{background:var(--table-head); font-weight:650; white-space:nowrap}
#content tr:nth-child(even) td{background:#fafbfc}
/* Obsidian 双链在 html 里无法解析，做成带标识的引用样式，不假装是链接 */
.wikilink{color:var(--accent); cursor:help; white-space:nowrap}
.wikilink::before{content:"[["; opacity:.4}
.wikilink::after{content:"]]"; opacity:.4}
/* ---------- 图 ---------- */
.diagram{
  margin:26px 0; padding:20px 16px; background:var(--card);
  border:1px solid var(--border); border-radius:10px; overflow-x:auto; text-align:center;
}
.diagram-svg{max-width:100%; height:auto; display:inline-block}
.diagram-missing{
  margin:26px 0; padding:14px 18px; background:#fff8e6; border:1px solid #e8d5a0;
  border-radius:8px; color:#8a6d1f; font-size:13px;
}
/* ---------- 移动端 ---------- */
#toc-toggle{
  display:none; position:fixed; right:18px; bottom:18px; z-index:50;
  width:50px; height:50px; border-radius:50%; border:0; cursor:pointer;
  background:var(--sidebar); color:#fff; font-size:19px; box-shadow:0 3px 12px rgba(0,0,0,.25);
}
@media (max-width:960px){
  #toc{
    position:fixed; left:0; top:0; z-index:40; transform:translateX(-100%);
    transition:transform .22s ease; box-shadow:2px 0 18px rgba(0,0,0,.2);
  }
  #toc.open{transform:translateX(0)}
  #main{padding:32px 20px 100px}
  #toc-toggle{display:block}
}
@media print{
  #toc,#toc-toggle{display:none}
  #main{padding:0; max-width:none}
  .diagram,}
</style>
</head>
<body>
<div id="layout">
  <nav id="toc"><div class="toc-title">目录</div><div id="toc-list"></div></nav>
  <main id="main"><article id="content"></article></main>
</div>
<button id="toc-toggle" aria-label="目录">☰</button>

<script>__MARKED_JS__</script>
<script id="md-src" type="text/plain">__MD_B64__</script>
<script>
(function () {
  "use strict";

  // 1. 解出内嵌的 markdown 源码（base64，避免任何转义问题）
  var b64 = document.getElementById("md-src").textContent.trim();
  var bytes = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
  var raw = new TextDecoder("utf-8").decode(bytes);

  // 2. Obsidian 双链 [[笔记]] / [[笔记|显示]] 在浏览器里无从解析，
  //    转成带 [[ ]] 标识的引用样式，既不丢信息也不假装可点。
  //    按代码块切分处理，避免误伤代码里的 [[ ]]。
  function renderWikilinks(md) {
    return md.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map(function (part, i) {
      if (i % 2 === 1) { return part; }
      return part.replace(/\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]/g,
        function (m, target, display) {
          var text = display || target;
          var kind = target.charAt(0) === "#" ? "本文章节" : "关联笔记";
          return '<span class="wikilink" title="' + kind + "：" + target + '">' + text + "</span>";
        });
    }).join("");
  }

  marked.setOptions({ gfm: true, breaks: false });
  document.getElementById("content").innerHTML = marked.parse(renderWikilinks(raw));
  var content = document.getElementById("content");

  // 3. 生成侧边目录（h2 一级、h3 二级）
  function slugify(text) {
    return text.trim().toLowerCase()
      .replace(/[^\w一-龥\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "section";
  }

  var used = Object.create(null);
  var tocList = document.getElementById("toc-list");
  var headings = content.querySelectorAll("h2, h3");

  headings.forEach(function (h) {
    var base = slugify(h.textContent);
    var id = base, n = 2;
    while (used[id]) { id = base + "-" + n++; }
    used[id] = true;
    h.id = id;

    var a = document.createElement("a");
    a.href = "#" + id;
    a.textContent = h.textContent;
    if (h.tagName === "H3") { a.className = "lv3"; }
    a.dataset.target = id;
    tocList.appendChild(a);
  });

  // 4. 滚动高亮当前章节
  var links = Array.prototype.slice.call(tocList.querySelectorAll("a"));
  var byId = Object.create(null);
  links.forEach(function (a) { byId[a.dataset.target] = a; });

  if ("IntersectionObserver" in window && links.length) {
    var visible = Object.create(null);
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { visible[e.target.id] = true; }
        else { delete visible[e.target.id]; }
      });
      var current = null;
      headings.forEach(function (h) {
        if (!current && visible[h.id]) { current = h.id; }
      });
      if (current) {
        links.forEach(function (a) { a.classList.remove("active"); });
        if (byId[current]) { byId[current].classList.add("active"); }
      }
    }, { rootMargin: "-10% 0px -70% 0px", threshold: 0 });
    headings.forEach(function (h) { observer.observe(h); });
  }

  // 5. 移动端目录开关
  var toggle = document.getElementById("toc-toggle");
  var toc = document.getElementById("toc");
  toggle.addEventListener("click", function () { toc.classList.toggle("open"); });
  toc.addEventListener("click", function (e) {
    if (e.target.tagName === "A") { toc.classList.remove("open"); }
  });

})();
</script>
</body>
</html>
"""


def build(md_path, out_path=None, open_after=False, do_render=True):
    """把 markdown 渲染为单文件自包含 HTML，返回输出路径。"""
    md_path = os.path.abspath(md_path)
    if not os.path.isfile(md_path):
        sys.exit("找不到 markdown 文件：%s" % md_path)

    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()

    base_dir = os.path.dirname(md_path)
    out_path = os.path.abspath(out_path) if out_path else os.path.splitext(md_path)[0] + ".html"

    # 1. 渲染 PlantUML 图
    notes = []
    diagrams_dir = os.path.join(base_dir, "diagrams")
    if do_render and os.path.isdir(diagrams_dir):
        count, msg = render_plantuml(diagrams_dir)
        notes.append(msg)

    # 2. 内联 SVG
    md, missing = inline_diagrams(md, base_dir)
    if missing:
        notes.append("⚠ 以下图未找到：%s" % "、".join(missing))

    # 3. frontmatter 是给 Obsidian 看的元数据，HTML 正文里不该出现
    frontmatter, md = split_frontmatter(md)
    title = extract_title(frontmatter, md, os.path.splitext(os.path.basename(md_path))[0])
    body_md = strip_toc_section(md).lstrip("\n")
    md_b64 = base64.b64encode(body_md.encode("utf-8")).decode("ascii")

    page = (
        HTML_TEMPLATE
        .replace("__TITLE__", title.replace("<", "&lt;").replace(">", "&gt;"))
        .replace("__MARKED_JS__", read_asset("marked.min.js"))
        .replace("__MD_B64__", md_b64)
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)

    size = os.path.getsize(out_path)
    human = "%.1f MB" % (size / 1024.0 / 1024.0) if size > 1024 * 1024 else "%d KB" % (size / 1024)
    for n in notes:
        print("  · %s" % n)
    print("已生成：%s（%s，离线自包含）" % (out_path, human))

    if open_after:
        subprocess.run(["open", out_path], check=False)

    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="把 clarify 的需求澄清 markdown 渲染为单文件自包含 HTML"
    )
    parser.add_argument("markdown", help="需求澄清 markdown 文件路径")
    parser.add_argument("-o", "--output", help="输出 html 路径，默认与 md 同目录同名")
    parser.add_argument("--open", action="store_true", dest="open_after", help="生成后用浏览器打开")
    parser.add_argument("--no-render", action="store_false", dest="do_render",
                        help="跳过 PlantUML 渲染，直接用已有 svg")
    args = parser.parse_args()
    build(args.markdown, args.output, args.open_after, args.do_render)


if __name__ == "__main__":
    main()
