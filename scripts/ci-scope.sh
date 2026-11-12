#!/usr/bin/env bash
# 判断本次改动是否触及某条栈,输出 `run=true` 或 `run=false`(供 $GITHUB_OUTPUT)。
#
# 为什么需要它
# ------------
# required status check 必须**每次 PR 都出现**,但后端/网页端的重活(装依赖 + 起 MySQL
# + 全量测试,5–10 分钟)不该在每个 PR 都跑 —— 这个项目的开发频率很高。
# 折中是:workflow 不再按 paths 过滤(job 总是出现),job 内部按改动面决定要不要做重活。
# 无关时秒级结束,check 结论仍是 success,required 满足;相关时才跑全量。
#
# fail-closed
# -----------
# 判定失败(API 报错 / 解析不出文件 / 事件类型不认识)一律输出 `run=true`:
# 宁可多跑一次,也不能因为判定器坏了把门禁静默跳过。
#
# 用法
# ----
#   bash scripts/ci-scope.sh backend
#   bash scripts/ci-scope.sh web
#   FILES_FROM=changed.txt bash scripts/ci-scope.sh backend   # 自测用:不联网
#
# 环境变量(workflow 里注入):EVENT / REPO / PR_NUMBER / BEFORE / AFTER / GH_TOKEN
set -uo pipefail

STACK=${1:-}
case "$STACK" in
  backend)
    PATTERN='^(chatapp/|perf/|docs/api/|app/pubspec\.yaml|\.github/workflows/backend\.yml)'
    ;;
  web)
    PATTERN='^(web/|docs/api/|imserver/tests/fixtures/|\.github/workflows/web\.yml)'
    ;;
  *)
    echo "用法: $0 <backend|web>" >&2
    exit 2
    ;;
esac

EVENT=${EVENT:-}
REPO=${REPO:-}
FILES_FROM=${FILES_FROM:-}

# 自测路径:直接读文件列表,不联网
if [ -n "$FILES_FROM" ]; then
  files=$(cat "$FILES_FROM" 2>/dev/null) || files=""
else
  case "$EVENT" in
    workflow_dispatch)
      # 人主动触发 = 明确要跑
      echo "run=true"
      exit 0
      ;;
    pull_request)
      # PR 文件数可能超过 100,--paginate 会翻页
      files=$(gh api --paginate "repos/$REPO/pulls/${PR_NUMBER}/files?per_page=100" \
        --jq '.[].filename' 2>/dev/null) || files=""
      ;;
    push)
      # compare API 最多返回 300 个文件;到上限就当「判不出来」→ 全跑
      if [ -n "${BEFORE:-}" ] && [ "$BEFORE" != "0000000000000000000000000000000000000000" ]; then
        body=$(gh api "repos/$REPO/compare/${BEFORE}...${AFTER}" 2>/dev/null) || body=""
        count=$(printf '%s' "$body" | jq '.files | length' 2>/dev/null || echo 0)
        if [ "${count:-0}" -ge 300 ]; then
          files=""
        else
          files=$(printf '%s' "$body" | jq -r '.files[].filename' 2>/dev/null) || files=""
        fi
      fi
      ;;
    *)
      files=""
      ;;
  esac
fi

# 判不出来 → 跑(fail-closed)
if [ -z "${files:-}" ]; then
  echo "run=true"
  exit 0
fi

if printf '%s\n' "$files" | grep -qE "$PATTERN"; then
  echo "run=true"
else
  echo "run=false"
fi
