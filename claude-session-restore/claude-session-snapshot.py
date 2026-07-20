#!/usr/bin/env python3
"""重启前手动运行：把当前 Warp 里所有 claude 会话（含真实分屏结构、精确到具体格子）
记录下来，生成 Warp Tab Config，重启后配合 claude-restore-sessions.sh 恢复。

精确定位靠的是：每个 Warp pane 里的进程环境变量都有 WARP_TERMINAL_SESSION_UUID，
跟 Warp 自己 sqlite 状态库里 terminal_panes.uuid 是完全一样的值——不用再靠 cwd 瞎猜顺序。
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psutil

HOME = Path.home()
SKILL_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = HOME / ".claude" / "sessions"
TAB_CONFIG_DIR = HOME / ".warp" / "tab_configs"
# 每份存档独立存到 snapshots/<sid>/ 下（manifest.txt + meta.txt），保留最近 KEEP_SNAPSHOTS 份，
# 恢复时可以在多份历史存档里挑，不再是只能恢复最新的那一份。
SNAPSHOTS_DIR = SKILL_DIR / "snapshots"
KEEP_SNAPSHOTS = 10
# 新版 tab-config 命名：claude-restore-<sid>-<n>，sid 是纯数字时间戳；用它反查某份存档的所有 config。
NAME_RE = re.compile(r"^claude-restore-(\d+)-\d+$")
# 旧版单份 manifest，仅用于清理遗留文件。
LEGACY_MANIFEST = SKILL_DIR / "claude-restore-manifest.txt"
LEGACY_MANIFEST_META = SKILL_DIR / "claude-restore-manifest.meta"
WARP_DB = (
    HOME
    / "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support"
    / "dev.warp.Warp-Stable/warp.sqlite"
)
RESUME_CMD = "mc --code --dangerously-skip-permissions --resume {session_id}"


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


def collect_live_sessions():
    """扫描 ~/.claude/sessions/*.json，只保留：进程存活 + 挂真实 tty + 归属 Warp 的会话。"""
    sessions = []
    if not SESSIONS_DIR.is_dir():
        return sessions
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            pid = int(f.stem)
        except ValueError:
            continue
        if not is_alive(pid):
            continue
        tty = get_tty(pid)
        if not tty or tty == "??":
            continue
        pane_uuid = get_warp_pane_uuid(pid)
        if not pane_uuid:
            print(f"  跳过 pid={pid}：不是 Warp 里的会话（可能在 IntelliJ/iTerm/远程终端等其他地方）", file=sys.stderr)
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        session_id = data.get("sessionId")
        cwd = data.get("cwd")
        if not session_id or not cwd:
            continue
        sessions.append({
            "pid": pid,
            "session_id": session_id,
            "cwd": cwd,
            "tty": tty,
            "pane_uuid": pane_uuid,
            "stopped": is_stopped(pid),
        })
    return sessions


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


def match_sessions_to_tree(tabs, live_sessions):
    """按 WARP_TERMINAL_SESSION_UUID 精确匹配到树里的叶子——不是猜的，是精确对应。
    DB 还没同步到的（刚开的新 pane）匹配不上，留作 leftover 单独处理。
    同一个 pane_uuid 对应多个存活会话时（比如 Ctrl-Z 挂起了一个旧的又在同一个格子里另起了新的），
    只保留没被挂起的那个，被挂起的直接丢弃（恢复一个已经不在前台的任务没有意义）。"""
    by_uuid = {}
    for s in live_sessions:
        existing = by_uuid.get(s["pane_uuid"])
        if existing is None:
            by_uuid[s["pane_uuid"]] = s
        elif existing["stopped"] and not s["stopped"]:
            print(f"  pid={existing['pid']} 和 pid={s['pid']} 是同一个 pane，丢弃被挂起的 pid={existing['pid']}", file=sys.stderr)
            by_uuid[s["pane_uuid"]] = s
        elif s["stopped"] and not existing["stopped"]:
            print(f"  pid={existing['pid']} 和 pid={s['pid']} 是同一个 pane，丢弃被挂起的 pid={s['pid']}", file=sys.stderr)
    matched_uuids = set()

    assignment = {}
    for tab_id, tab in tabs.items():
        for node_id, n in tab["nodes"].items():
            if n["is_leaf"] and n["cwd"]:
                session = by_uuid.get(n["pane_uuid"])
                assignment[(tab_id, node_id)] = session
                if session:
                    matched_uuids.add(n["pane_uuid"])

    leftover = [s for s in live_sessions if s["pane_uuid"] not in matched_uuids]
    return assignment, leftover


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
                cmd = RESUME_CMD.format(session_id=session["session_id"])
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
    for f in TAB_CONFIG_DIR.glob("claude-restore-*.toml"):
        m = NAME_RE.match(f.stem)
        if not m or m.group(1) not in valid_sids:
            f.unlink()


def main():
    TAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    # 清理旧版单份 manifest，新版改用 snapshots/<sid>/ 存档目录。
    for legacy in (LEGACY_MANIFEST, LEGACY_MANIFEST_META):
        if legacy.exists():
            legacy.unlink()

    now = datetime.now()
    sid = now.strftime("%Y%m%d%H%M%S")

    print("扫描存活的 Claude Code 会话...")
    live_sessions = collect_live_sessions()

    print("读取 Warp 真实分屏布局...")
    tabs = load_warp_pane_tree()
    assignment, leftover = match_sessions_to_tree(tabs, live_sessions)

    manifest_names = []
    counter = 0
    matched_count = 0

    for tab_id, tab in sorted(tabs.items()):
        chunks = render_tab_chunks(tab_id, tab, assignment)
        if not chunks:
            continue
        counter += 1
        name = f"claude-restore-{sid}-{counter}"
        write_tab_config(name, chunks)
        manifest_names.append(name)
        leaf_count = sum(1 for c in chunks if any(l.startswith("directory =") for l in c))
        hit_count = sum(
            1
            for (tid, nid), s in assignment.items()
            if tid == tab_id and s is not None
        )
        matched_count += hit_count
        print(f"  [{name}] 精确还原 {leaf_count} 个 pane 的分屏布局（{hit_count} 个接上了会话）")

    for s in leftover:
        counter += 1
        name = f"claude-restore-{sid}-{counter}"
        chunk = [
            "[[panes]]",
            'id = "main"',
            'type = "terminal"',
            f'directory = "{toml_escape(s["cwd"])}"',
            f'commands = ["{toml_escape(RESUME_CMD.format(session_id=s["session_id"]))}"]',
        ]
        write_tab_config(name, [chunk])
        manifest_names.append(name)
        print(f"  [{name}] {s['cwd']}（session {s['session_id']}，DB 里没找到对应 pane，单独开一个 tab）")
        matched_count += 1

    print("")
    if not manifest_names:
        # 这次没扫到会话，不落存档，也顺手同步一下 tab-config（保留已有历史存档）。
        sync_tab_configs(prune_snapshots())
        print("没有找到可恢复的会话")
        return

    # 1. 把本次存档的清单和元信息写到独立的 snapshots/<sid>/ 目录
    snap_dir = SNAPSHOTS_DIR / sid
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "manifest.txt").write_text("\n".join(manifest_names) + "\n")
    (snap_dir / "meta.txt").write_text(
        f"{now:%Y-%m-%d %H:%M:%S}\n{matched_count}\n{len(manifest_names)}\n"
    )

    # 2. 只保留最近 KEEP_SNAPSHOTS 份存档，并清掉不属于有效存档的 tab-config
    valid_sids = prune_snapshots()
    valid_sids.add(sid)
    sync_tab_configs(valid_sids)

    print(f"共记录 {matched_count} 个会话，生成 {len(manifest_names)} 个 tab-config")
    print(f"存档 ID：{sid}（{now:%Y-%m-%d %H:%M:%S}），已保留最近 {len(valid_sids)} 份存档")
    print("重启后运行 claude-restore-sessions.sh --list 查看并选择要恢复的存档")


if __name__ == "__main__":
    main()
