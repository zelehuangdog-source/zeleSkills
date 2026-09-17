#!/usr/bin/env python3
"""重启前手动运行：把当前 Warp 里所有 agent 会话（Claude Code + Grok，含真实分屏结构、
精确到具体格子）记录下来，生成 Warp Tab Config，重启后配合 agent-restore-sessions.sh 恢复。

精确定位靠的是：每个 Warp pane 里的进程环境变量都有 WARP_TERMINAL_SESSION_UUID，
跟 Warp 自己 sqlite 状态库里 terminal_panes.uuid 是完全一样的值——不用再靠 cwd 瞎猜顺序。

两个 agent 的会话索引来源不同：
  - Claude Code：~/.claude/sessions/<pid>.json，一个进程一个文件，内含 sessionId/cwd/startedAt。
  - Grok：~/.grok/active_sessions.json，一张存活登记表（session_id/pid/cwd/opened_at）。
    grok 进程自身的环境变量里没有 GROK_SESSION_ID（它只注入给子进程），所以 pid → session_id
    得靠这张表，或者靠进程命令行里的 `--resume <session_id>`（这张表会漏登活着的会话，
    所以进程表那一路是必备的兜底，见 collect_grok_process_sessions）。
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import psutil

HOME = Path.home()
SKILL_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = HOME / ".claude" / "sessions"
GROK_ACTIVE_SESSIONS = HOME / ".grok" / "active_sessions.json"
TAB_CONFIG_DIR = HOME / ".warp" / "tab_configs"
# 每份存档独立存到 snapshots/<sid>/ 下（manifest.txt + meta.txt），保留最近 KEEP_SNAPSHOTS 份，
# 恢复时可以在多份历史存档里挑，不再是只能恢复最新的那一份。
SNAPSHOTS_DIR = SKILL_DIR / "snapshots"
KEEP_SNAPSHOTS = 10
# 新版 tab-config 命名：agent-restore-<sid>-<n>，sid 是纯数字时间戳；用它反查某份存档的所有 config。
NAME_RE = re.compile(r"^agent-restore-(\d+)-\d+$")
# 旧版单份 manifest，仅用于清理遗留文件。
LEGACY_MANIFEST = SKILL_DIR / "agent-restore-manifest.txt"
LEGACY_MANIFEST_META = SKILL_DIR / "agent-restore-manifest.meta"
WARP_DB = (
    HOME
    / "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support"
    / "dev.warp.Warp-Stable/warp.sqlite"
)
# 恢复命令按 agent 分派。grok 用 --always-approve，与 claude 侧的 --dangerously-skip-permissions 对齐。
RESUME_CMD = {
    "claude": "mc --code --dangerously-skip-permissions --resume {session_id}",
    "grok": "grok --always-approve --resume {session_id}",
}
# 登记时间与进程启动时间允许的偏差上限（秒）：超过它说明登记表里的 pid 已被回收。
PID_REUSE_SLACK = 300
# 存档构成（meta.txt 第 4 行）里两个 agent 的固定顺序。
COMPOSITION_AGENTS = ("claude", "grok")
# grok 进程命令行里的 `--resume <session_id>`：session id 直接可见，不必经过登记表。
GROK_RESUME_RE = re.compile(r"--resume\s+([0-9a-fA-F-]{36})")


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def get_tty(pid):
    return sh("ps", "-p", str(pid), "-o", "tty=")


def is_stopped(pid):
    """判断进程是不是被 Ctrl-Z 挂起的后台任务（STAT 里带 T）。"""
    return "T" in sh("ps", "-p", str(pid), "-o", "stat=")


def get_warp_pane_uuid(pid):
    """读取该进程环境变量里的 WARP_TERMINAL_SESSION_UUID（没有就说明不是 Warp 里的 pane，
    比如跑在 IntelliJ/iTerm/远程桌面工具打开的终端里）。"""
    try:
        env = psutil.Process(pid).environ()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    uuid = env.get("WARP_TERMINAL_SESSION_UUID")
    return uuid.lower() if uuid else None


def toml_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def pid_recycled(pid, started):
    """判断登记表里那个 pid 是不是已经被系统回收给了别的进程（该会话其实早退出了）。

    真会话进程的启动时间不会晚于它自己的登记时间——grok 的 opened_at 实测比进程启动晚
    8~19 秒（启动初始化）；claude 的 <pid>.json 是进程一起来就写（二进制里那行
    `startedAt: Date.now()`，同一条记录里还带 `procStart`），所以"进程比登记时间晚 5 分钟
    以上才启动"只可能是 pid 复用。不排掉的话，pid 落到哪个格子，这个早死掉的会话就会被算成
    那个格子里一个活着的会话。started 缺失（0）时无从判断，放行。"""
    if not started:
        return False
    try:
        return psutil.Process(pid).create_time() > started + PID_REUSE_SLACK
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def pane_session(agent, pid, session_id, cwd, started):
    """把一条原始记录归一成统一形态；只保留"进程存活 + 挂真实 tty + 归属 Warp"的会话。"""
    if not is_alive(pid):
        return None
    if not session_id or not cwd:
        return None
    tty = get_tty(pid)
    if not tty or tty == "??":
        return None
    pane_uuid = get_warp_pane_uuid(pid)
    if not pane_uuid:
        print(f"  跳过 pid={pid}（{agent}）：不是 Warp 里的会话（可能在 IntelliJ/iTerm/远程终端等其他地方）", file=sys.stderr)
        return None
    if pid_recycled(pid, started):
        print(
            f"  跳过 {agent}/{session_id[:8]}（pid={pid}）：登记表里的 pid 已被回收"
            "（该进程启动时间晚于会话登记时间），这不是那个会话的进程",
            file=sys.stderr,
        )
        return None
    return {
        "agent": agent,
        "pid": pid,
        "session_id": session_id,
        "cwd": cwd,
        "tty": tty,
        "pane_uuid": pane_uuid,
        "stopped": is_stopped(pid),
        "started": started,
    }


def collect_claude_sessions():
    """扫描 ~/.claude/sessions/<pid>.json。这张登记表只记 claude 本体、不记 mc 启动壳，
    所以同一个 `mc --code` 格子天然只算一个会话，不会重复计数。"""
    sessions = []
    if not SESSIONS_DIR.is_dir():
        return sessions
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            pid = int(f.stem)
        except ValueError:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        s = pane_session(
            "claude",
            pid,
            data.get("sessionId"),
            data.get("cwd"),
            (data.get("startedAt") or 0) / 1000.0,
        )
        if s:
            sessions.append(s)
    return sessions


def collect_grok_sessions():
    """读 ~/.grok/active_sessions.json：grok 进程自身的环境变量里没有 GROK_SESSION_ID
    （只注入给子进程），pid → session_id 只能靠这张登记表；进程退出后条目会被移除。"""
    sessions = []
    if not GROK_ACTIVE_SESSIONS.is_file():
        return sessions
    try:
        entries = json.loads(GROK_ACTIVE_SESSIONS.read_text())
    except Exception:
        return sessions
    for e in entries:
        started = 0.0
        try:
            started = datetime.fromisoformat(str(e["opened_at"]).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
        s = pane_session("grok", int(e["pid"]), e.get("session_id"), e.get("cwd"), started)
        if s:
            sessions.append(s)
    return sessions


def collect_grok_process_sessions():
    """从进程表补 grok 会话：`grok --always-approve --resume <session_id>` 的 session id 就写在
    命令行里，cwd 和 pane uuid 也能直接从进程取，用不着登记表。

    为什么必须补：登记表会漏。2026-09-17 实测，12 个活着的 grok 进程只登记了 8 个（漏掉的
    包括 `01a0a94d`、`01a0aa2f-b2d0`），只按登记表存档会让这些会话直接消失。

    带 `--fork-session` 的进程跳过：它的命令行写的是被 fork 的**父**会话 id，而它自己是一个
    新会话——按命令行记会把父会话安到 fork 的格子上，比漏掉更糟。这类会话仍由登记表覆盖。"""
    sessions = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(proc.info["cmdline"] or [])
            name = proc.info["name"] or ""
            if "grok" not in name and "/grok" not in cl:
                continue
            if "--fork-session" in cl:
                continue
            m = GROK_RESUME_RE.search(cl)
            if not m:
                continue
            pid = proc.info["pid"]
            s = pane_session("grok", pid, m.group(1), proc.cwd(), proc.create_time())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if s:
            sessions.append(s)
    return sessions


def collect_live_sessions():
    """收集所有存活的 agent 会话（claude + grok 混合）。

    grok 有登记表和进程表两路来源，按 (agent, session_id, pane_uuid) 去重、进程表那条覆盖
    登记表那条——它的 pid 按定义就是活着的进程。去重键里带上 pane_uuid 是故意的：同一个会话
    出现在两个格子里（用户有意 --resume 两次）是两件事，各归各的格子，不能合并掉；要合并的
    只是"同一个会话在同一个格子里被两路各报了一次"。"""
    merged = {}
    for s in collect_claude_sessions() + collect_grok_sessions() + collect_grok_process_sessions():
        merged[(s["agent"], s["session_id"], s["pane_uuid"])] = s
    return list(merged.values())


def load_warp_pane_tree():
    """读 Warp 自己的 sqlite，拿真实的 window/tab/分屏树，每个叶子带上它的 pane uuid。
    读不到就返回空字典，上层会整体退化成每个会话单独一个 tab。"""
    tabs = {}
    if not WARP_DB.is_file():
        print("  没找到 Warp 的 sqlite 状态库，分屏布局会退化成每个会话单独一个 tab", file=sys.stderr)
        return tabs
    try:
        conn = sqlite3.connect(f"file:{WARP_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.id, t.custom_title, pn.id, pn.parent_pane_node_id, pn.is_leaf, pb.horizontal,
                   tp.cwd, hex(tp.uuid)
            FROM tabs t
            JOIN pane_nodes pn ON pn.tab_id = t.id
            LEFT JOIN pane_branches pb ON pb.pane_node_id = pn.id
            LEFT JOIN terminal_panes tp ON tp.id = pn.id
            WHERE pn.is_leaf = 0 OR tp.cwd IS NOT NULL
            ORDER BY t.id, pn.id
            """
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"  读取 Warp 分屏布局失败（{e}），分屏布局会退化成每个会话单独一个 tab", file=sys.stderr)
        return tabs

    for tab_id, title, node_id, parent_id, is_leaf, horizontal, cwd, uuid_hex in rows:
        tab = tabs.setdefault(tab_id, {"title": title, "nodes": {}})
        tab["nodes"][node_id] = {
            "parent": parent_id,
            "is_leaf": bool(is_leaf),
            "horizontal": horizontal,
            "cwd": cwd,
            "pane_uuid": uuid_hex.lower() if uuid_hex else None,
        }
    return tabs


def rank_sessions(sessions):
    """同一格子里多个会话的排序：没被 Ctrl-Z 挂起的优先，其次启动更晚的（更可能是你重启前正在用的）。"""
    return sorted(sessions, key=lambda s: (s["stopped"], -s["started"]))


def ancestors(pid, limit=12):
    """从 pid 往上收集祖先进程号，用来判断一个会话是不是在别的会话进程里嵌套起的。"""
    chain = []
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return chain
    for _ in range(limit):
        try:
            proc = proc.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return chain
        if proc is None:
            return chain
        chain.append(proc.pid)
    return chain


def split_nested(group):
    """把一个格子里的多个会话拆成「独立会话」和「嵌套会话」（后者附带原因）。

    两类不算独立格子：
    1. 嵌套启动——它的进程祖先链里坐着同格子里另一个会话的进程：它是被那个会话在同一格子
       里拉起来的（agent 的 shell 工具、或在同一个格子里跑挂的 fork），本身不占独立格子。
       2026-09-16 20:34 的日志实测过：登记的 pid 67069 同时挂着 01a0a962 和 01a0aa2c 两个
       session_id，这种格子在存档里就会凭空多出两个 tab。
    2. 同一个 pid——一个进程只有一个终端画面，登记表却能把一个 pid 记在多个 session_id 下。

    对照组：先 Ctrl-Z 挂起 A、再在同一个格子里开 B，B 的 pid 与祖先链里都没有 A，仍算独立。"""
    pids = {s["pid"] for s in group}
    independent, nested = [], []
    seen_pid = set()
    for s in group:
        if s["pid"] in seen_pid:
            nested.append((s, "登记表把同一个 pid 记在了多个会话上，一个进程只有一个终端画面"))
        elif set(ancestors(s["pid"])) & (pids - {s["pid"]}):
            nested.append((s, "它是在同一个格子里由别的会话嵌套起的"))
        else:
            seen_pid.add(s["pid"])
            independent.append(s)
    return independent, nested


def match_sessions_to_tree(tabs, live_sessions):
    """按 WARP_TERMINAL_SESSION_UUID 精确匹配到树里的叶子——不是猜的，是精确对应。
    DB 还没同步到的（刚开的新 pane）匹配不上，留作 leftover 单独处理。

    一个格子里有多个"真正独立"的会话时（先 Ctrl-Z 挂了 A 又开了 B），一个格子只有一个终端
    画面、塞不下两个：排序后第一个回原格子，其余作为 extra 另开 tab，会话内容都不丢。注意
    `mc --code` 的 mc+claude 是两个进程但只有一个会话，不在此列。
    另外两类不算"独立会话"：同一格子里嵌套起的、登记表里 pid 已被回收的（见 pid_recycled）——
    前者在匹配前就排掉，后者在收集阶段就已经排掉。"""
    by_uuid = defaultdict(list)
    for s in live_sessions:
        by_uuid[s["pane_uuid"]].append(s)

    assignment = {}
    extras = []
    matched_uuids = set()
    for tab_id, tab in tabs.items():
        for node_id, n in tab["nodes"].items():
            if not (n["is_leaf"] and n["cwd"]):
                continue
            group = rank_sessions(by_uuid.get(n["pane_uuid"], []))
            if len(group) > 1:
                group, nested = split_nested(group)
                for s, why in nested:
                    print(
                        f"  跳过 {s['agent']}/{s['session_id'][:8]}：{why}（不是独立终端格子），不单独开 tab",
                        file=sys.stderr,
                    )
            assignment[(tab_id, node_id)] = group[0] if group else None
            if group:
                matched_uuids.add(n["pane_uuid"])
                if len(group) > 1:
                    keep, rest = group[0], group[1:]
                    extras.extend(rest)
                    print(
                        f"  格子 {n['pane_uuid'][:8]} 里有 {len(group)} 个独立会话，"
                        f"保留 {keep['agent']}/{keep['session_id'][:8]}，另外 {len(rest)} 个各开一个 tab",
                        file=sys.stderr,
                    )

    leftover = [s for s in live_sessions if s["pane_uuid"] not in matched_uuids]
    return assignment, extras, leftover


def render_tab_chunks(tab_id, tab, assignment):
    """把一个 tab 的分屏树递归渲染成 [[panes]] 代码块列表；单子节点的空分支会被压平。"""
    nodes = tab["nodes"]
    children_map = defaultdict(list)
    root_id = None
    for nid, n in nodes.items():
        if n["parent"] is None:
            root_id = nid
        else:
            children_map[n["parent"]].append(nid)

    chunks = []

    def visit(node_id, pane_id_override=None):
        n = nodes[node_id]
        pane_id = pane_id_override or f"p{node_id}"
        if n["is_leaf"]:
            cwd = n["cwd"] or ""
            session = assignment.get((tab_id, node_id))
            block = [
                "[[panes]]",
                f'id = "{pane_id}"',
                'type = "terminal"',
                f'directory = "{toml_escape(cwd)}"',
            ]
            if session:
                cmd = RESUME_CMD[session["agent"]].format(session_id=session["session_id"])
                block.append(f'commands = ["{toml_escape(cmd)}"]')
            chunks.append(block)
            return pane_id

        raw_children = [c for c in sorted(children_map.get(node_id, [])) if c in nodes]
        rendered_ids = [rid for rid in (visit(c) for c in raw_children) if rid]
        if not rendered_ids:
            return None
        if len(rendered_ids) == 1:
            return rendered_ids[0]  # 只剩一个孩子的分支，直接压平成那个孩子

        split_dir = "horizontal" if n["horizontal"] else "vertical"
        children_list = ", ".join(f'"{c}"' for c in rendered_ids)
        chunks.append(
            [
                "[[panes]]",
                f'id = "{pane_id}"',
                f'split = "{split_dir}"',
                f"children = [{children_list}]",
            ]
        )
        return pane_id

    if root_id is None:
        return None
    root_pane_id = visit(root_id, pane_id_override="root")
    if root_pane_id is None:
        return None

    # Warp 认根节点的规则是"文件里第一个 [[panes]] 条目"，不是看 id 叫什么。
    # 上面是后序遍历，根节点的代码块本来会被追加在最后，这里挪到最前面。
    root_index = next(i for i, block in enumerate(chunks) if block[1] == f'id = "{root_pane_id}"')
    chunks.insert(0, chunks.pop(root_index))
    return chunks


def write_tab_config(name, chunks):
    lines = [f'name = "{toml_escape(name)}"', ""]
    for block in chunks:
        lines.extend(block)
        lines.append("")
    (TAB_CONFIG_DIR / f"{name}.toml").write_text("\n".join(lines))


def prune_snapshots():
    """只保留最近 KEEP_SNAPSHOTS 份存档目录，删掉更旧的，返回仍然有效的 sid 集合。"""
    if not SNAPSHOTS_DIR.is_dir():
        return set()
    snaps = sorted(
        (d for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: d.name,
        reverse=True,
    )
    for d in snaps[KEEP_SNAPSHOTS:]:
        shutil.rmtree(d, ignore_errors=True)
    return {d.name for d in snaps[:KEEP_SNAPSHOTS]}


def sync_tab_configs(valid_sids):
    """删除不属于任何有效存档的 tab-config（含旧版无 sid 命名的遗留文件），避免无限堆积。"""
    for f in TAB_CONFIG_DIR.glob("agent-restore-*.toml"):
        m = NAME_RE.match(f.stem)
        if not m or m.group(1) not in valid_sids:
            f.unlink()


def single_pane_config(session):
    """把一个接不进分屏树的会话渲染成"单个 pane 的 tab"。"""
    return [
        "[[panes]]",
        'id = "main"',
        'type = "terminal"',
        f'directory = "{toml_escape(session["cwd"])}"',
        f'commands = ["{toml_escape(RESUME_CMD[session["agent"]].format(session_id=session["session_id"]))}"]',
    ]


def main():
    TAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    # 清理旧版单份 manifest，新版改用 snapshots/<sid>/ 存档目录。
    for legacy in (LEGACY_MANIFEST, LEGACY_MANIFEST_META):
        if legacy.exists():
            legacy.unlink()

    now = datetime.now()
    sid = now.strftime("%Y%m%d%H%M%S")

    print("扫描存活的 agent 会话（Claude Code + Grok）...")
    live_sessions = collect_live_sessions()

    print("读取 Warp 真实分屏布局...")
    tabs = load_warp_pane_tree()
    assignment, extras, leftover = match_sessions_to_tree(tabs, live_sessions)

    manifest_names = []
    counter = 0
    matched_count = 0
    # 真正写进 tab-config 的会话，用来把这份存档的构成（各 agent 多少个格子）固化在存档里。
    written = []

    for tab_id, tab in sorted(tabs.items()):
        chunks = render_tab_chunks(tab_id, tab, assignment)
        if not chunks:
            continue
        counter += 1
        name = f"agent-restore-{sid}-{counter}"
        write_tab_config(name, chunks)
        manifest_names.append(name)
        leaf_count = sum(1 for c in chunks if any(l.startswith("directory =") for l in c))
        tab_sessions = [
            s for (tid, nid), s in assignment.items() if tid == tab_id and s is not None
        ]
        written.extend(tab_sessions)
        matched_count += len(tab_sessions)
        print(f"  [{name}] 精确还原 {leaf_count} 个 pane 的分屏布局（{len(tab_sessions)} 个接上了会话）")

    # 同一个格子里多出来的独立会话：一个格子只有一个终端画面，塞不下两个，各自开一个 tab。
    for s in extras:
        counter += 1
        name = f"agent-restore-{sid}-{counter}"
        write_tab_config(name, [single_pane_config(s)])
        manifest_names.append(name)
        print(f"  [{name}] {s['cwd']}（{s['agent']} session {s['session_id']}，与同格子里的另一个会话并存，单独开一个 tab）")
        written.append(s)
        matched_count += 1

    for s in leftover:
        counter += 1
        name = f"agent-restore-{sid}-{counter}"
        write_tab_config(name, [single_pane_config(s)])
        manifest_names.append(name)
        print(f"  [{name}] {s['cwd']}（{s['agent']} session {s['session_id']}，DB 里没找到对应 pane，单独开一个 tab）")
        written.append(s)
        matched_count += 1

    print("")
    if not manifest_names:
        # 这次没扫到会话，不落存档，也顺手同步一下 tab-config（保留已有历史存档）。
        sync_tab_configs(prune_snapshots())
        print("没有找到可恢复的会话")
        return

    # 1. 把本次存档的清单和元信息写到独立的 snapshots/<sid>/ 目录
    #    第 4 行是这份存档的构成（各 agent 占多少个格子），在存档时就固化下来：恢复脚本据此
    #    判断要不要问 claude 的启动命令，读的是存档自己，不去翻会被恢复过程改写/删掉的
    #    ~/.warp/tab_configs —— 否则"存档构成"会变成一个随时间漂移的外部状态。
    agents = Counter(s["agent"] for s in written)
    snap_dir = SNAPSHOTS_DIR / sid
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "manifest.txt").write_text("\n".join(manifest_names) + "\n")
    (snap_dir / "meta.txt").write_text(
        f"{now:%Y-%m-%d %H:%M:%S}\n{matched_count}\n{len(manifest_names)}\n"
        f"{COMPOSITION_AGENTS[0]} {agents[COMPOSITION_AGENTS[0]]} / "
        f"{COMPOSITION_AGENTS[1]} {agents[COMPOSITION_AGENTS[1]]}\n"
    )

    # 2. 只保留最近 KEEP_SNAPSHOTS 份存档，并清掉不属于有效存档的 tab-config
    valid_sids = prune_snapshots()
    valid_sids.add(sid)
    sync_tab_configs(valid_sids)

    print(f"共记录 {matched_count} 个会话，生成 {len(manifest_names)} 个 tab-config")
    print(f"存档 ID：{sid}（{now:%Y-%m-%d %H:%M:%S}），已保留最近 {len(valid_sids)} 份存档")
    print("重启后运行 agent-restore-sessions.sh --list 查看并选择要恢复的存档")


if __name__ == "__main__":
    main()
