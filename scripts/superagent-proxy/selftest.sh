#!/bin/bash
# render-config.py 的离线自测:不联网、不碰真实配置、不需要 root。
#
# 为什么值得写:这个脚本是「坏订阅」的唯一防线。机场偶尔返回 HTML 错误页
# 或残缺 YAML,如果它被写进 config.yaml,mihomo 起不来 → worker 全断网 →
# 现场看起来像「代理没开」,极难排查。所以校验逻辑必须有测试兜着,
# 否则某次「顺手简化」就可能把它删掉。
#
# 用法:bash scripts/superagent-proxy/selftest.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
RENDER="$HERE/render-config.py"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

pass=0
fail=0
say() { printf '%-6s %s\n' "$1" "$2"; }
ok() { say "ok" "$1"; pass=$((pass + 1)); }
bad() { say "FAIL" "$1"; fail=$((fail + 1)); }

command -v python3 >/dev/null || { echo "需要 python3"; exit 2; }
python3 -c 'import yaml' 2>/dev/null || { echo "需要 pyyaml"; exit 2; }

# ---------- 造样本 ----------
make_sub() {
  # $1=输出文件 $2=节点数 $3=是否含 IEPL 名 $4=节点前缀
  python3 - "$@" <<'PY'
import sys, yaml
out, n, iepl, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4]
proxies = [{"name": f"{prefix}节点{i:02d}", "type": "trojan", "server": f"10.0.0.{i}", "port": 443}
           for i in range(n)]
if iepl:
    proxies[0]["name"] = "🇭🇰|香港-IEPL 01"
    proxies[1]["name"] = "🇸🇬|新加坡-IEPL 02"
    proxies[2]["name"] = "🇯🇵|日本-IEPL 03"
# 信息节点:必须被排除在测速组之外
proxies.append({"name": "剩余流量：76.65 GB", "type": "trojan", "server": "10.0.0.99", "port": 443})
cfg = {
    "mixed-port": 7890,
    "allow-lan": True,
    "bind-address": "*",
    "external-controller": "127.0.0.1:9090",
    "proxies": proxies,
    "proxy-groups": [
        {"name": "节点选择", "type": "select", "proxies": ["自动选择"] + [p["name"] for p in proxies]},
        {"name": "自动选择", "type": "url-test", "proxies": [p["name"] for p in proxies],
         "url": "http://cp.cloudflare.com", "interval": 7200},
    ],
    "rules": ["GEOIP,CN,DIRECT", "MATCH,节点选择"],
}
yaml.safe_dump(cfg, open(out, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY
}

run() { # $1=输入文件 $2=输出文件;返回渲染退出码
  python3 "$RENDER" --from-file "$1" --out "$2" --override "$HERE/override.yaml" 2>"$T/err"
}

check() { # $1=描述 $2=python 表达式(读到 cfg 后为真即通过) $3=配置文件(默认 $T/out.yaml)
  local target="${3:-$T/out.yaml}"
  if python3 - "$2" "$target" <<'PY'
import sys, yaml
expr, path = sys.argv[1], sys.argv[2]
cfg = yaml.safe_load(open(path, encoding="utf-8"))
sys.exit(0 if eval(expr, {"cfg": cfg}) else 1)
PY
  then ok "$1"; else bad "$1"; fi
}

# ---------- 1. 正常订阅 ----------
make_sub "$T/good.yaml" 12 1 "🇭🇰|香港-"
if run "$T/good.yaml" "$T/out.yaml"; then
  ok "正常订阅渲染成功"
  check "allow-lan 被强制为 false"        "cfg['allow-lan'] is False"
  check "bind-address 被强制为回环"       "cfg['bind-address'] == '127.0.0.1'"
  check "external-controller 改到 9091"   "cfg['external-controller'] == '127.0.0.1:9091'"
  check "github 测速组已注入"             "any(g['name']=='github' for g in cfg['proxy-groups'])"
  check "github 组测的是 GitHub"          "[g for g in cfg['proxy-groups'] if g['name']=='github'][0]['url'].startswith('https://api.github.com')"
  check "信息节点被排除在测速组之外"      "all('流量' not in p for p in [g for g in cfg['proxy-groups'] if g['name']=='github'][0]['proxies'])"
  check "github 组只收 IEPL 节点"         "all('IEPL' in p for p in [g for g in cfg['proxy-groups'] if g['name']=='github'][0]['proxies'])"
  check "节点选择 的默认出口是 github"    "[g for g in cfg['proxy-groups'] if g['name']=='节点选择'][0]['proxies'][0] == 'github'"
  check "rules 原样保留"                  "cfg['rules'][-1] == 'MATCH,节点选择'"
else
  bad "正常订阅渲染成功"; cat "$T/err"
fi

# ---------- 2. HTML 错误页 ----------
printf '<html><body>504 Gateway Timeout</body></html>\n' >"$T/html.txt"
if run "$T/html.txt" "$T/out2.yaml"; then
  bad "HTML 错误页应被拒绝"
else
  ok "HTML 错误页被拒绝(退出码非 0)"
fi
[ -s "$T/out2.yaml" ] && bad "被拒时不应写出配置" || ok "被拒时没有留下半个配置文件"

# ---------- 3. 节点数不足 ----------
make_sub "$T/few.yaml" 3 1 "🇭🇰|香港-"
if run "$T/few.yaml" "$T/out3.yaml"; then
  bad "节点过少应被拒绝"
else
  ok "节点过少被拒绝"
fi

# ---------- 4. 没有 IEPL(应降级但成功) ----------
make_sub "$T/noiepl.yaml" 12 0 "🇺🇸|美国-中转"
if run "$T/noiepl.yaml" "$T/out4.yaml"; then
  ok "无 IEPL 时仍渲染成功(降级)"
  check "无 IEPL 时不建 github 组" "not any(g['name']=='github' for g in cfg['proxy-groups'])" "$T/out4.yaml"
  check "无 IEPL 时默认出口仍是机场原组" \
    "[g for g in cfg['proxy-groups'] if g['name']=='节点选择'][0]['proxies'][0] == '自动选择'" "$T/out4.yaml"
else
  bad "无 IEPL 时应降级成功"; cat "$T/err"
fi

# ---------- 5. 原子性:输出目录只应留下目标文件 ----------
stray=$(find "$T" -maxdepth 1 -name '.config-*' | wc -l)
[ "$stray" -eq 0 ] && ok "没有残留临时文件" || bad "残留了 $stray 个临时文件"

# ---------- 6. 启动脚本的选路判定(2026-11-13:端口活 **且** 出网真通) ----------
# 为什么挂在这里:这是「7890 在听、出网 0%」唯一的机械防线 —— 旧判据只看端口,
# 于是永不回退、worker 全断而面板全绿。用例本身在 scripts/test_start_superagent.sh
# (纯离线:端口与探测都打桩),这里只负责让它进 contract 轨(不新增 workflow step)。
if bash "$HERE/../test_start_superagent.sh"; then
  ok "启动脚本选路判定自测(scripts/test_start_superagent.sh 全绿)"
else
  bad "启动脚本选路判定自测(scripts/test_start_superagent.sh 有失败)"
fi

echo "------------------------------------------------------------"
echo "通过 $pass,失败 $fail"
[ "$fail" -eq 0 ] || exit 1
