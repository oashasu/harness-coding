#!/usr/bin/env bash
# Harness Coding — 发布前自检
# 把"可发布形态"的收口成果固化成一条命令，发布/上架前跑一遍。
# 只做只读检查，不安装、不修改任何文件。
#
# 用法:
#   ./scripts/release-check.sh
# 退出码: 0=全部通过，1=存在失败项
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FAIL=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }
section() { printf '\n== %s ==\n' "$1"; }

echo "Harness Coding 发布前自检 (root: $REPO_ROOT)"

# ── 1. 依赖与入口 ──────────────────────────────────────────────
section "1. 依赖与入口"

if python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)' 2>/dev/null; then
  pass "Python >= 3.9 ($(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"
else
  fail "Python 版本低于 3.9"
fi

if python3 -c 'import jsonschema, yaml' 2>/dev/null; then
  pass "jsonschema / yaml 可导入"
else
  fail "jsonschema 或 yaml 无法导入（pip install -r requirements.txt）"
fi

if bash -n scripts/bootstrap.sh 2>/dev/null; then
  pass "bash -n scripts/bootstrap.sh"
else
  fail "scripts/bootstrap.sh 语法检查失败"
fi

# ── 2. 运行态边界 ──────────────────────────────────────────────
section "2. 运行态边界"

TRACKED_STATE="$(git ls-files | grep -E 'harness-(workflow-)?state\.json$' | grep -vE 'example|template' || true)"
if [ -z "$TRACKED_STATE" ]; then
  pass "无被追踪的活状态文件"
else
  fail "发现被追踪的活状态文件: $TRACKED_STATE"
fi

if [ -d .harness/templates ] && [ -n "$(ls -A .harness/templates 2>/dev/null)" ]; then
  pass ".harness/templates/ 存在且非空"
else
  fail ".harness/templates/ 缺失或为空"
fi

# init-workspace.py 依赖的模板源文件必须齐全
MISSING_TPL=""
for tpl in harness-state.template.json SESSION_BRIEF.template.md \
           experience.template.md preflight-result.template.json; do
  [ -f ".harness/templates/$tpl" ] || MISSING_TPL="$MISSING_TPL $tpl"
done
if [ -z "$MISSING_TPL" ]; then
  pass "init-workspace 所需模板齐全"
else
  fail "缺少模板源文件:$MISSING_TPL"
fi

if [ -f .harness/harness-state.example.json ]; then
  pass ".harness/harness-state.example.json 存在"
else
  fail ".harness/harness-state.example.json 缺失"
fi

# .gitignore 必须覆盖关键运行态路径
GI_MISSING=""
for pat in '.harness/state/harness-state.json' '.harness/output/' '.harness/logs/'; do
  grep -qF "$pat" .gitignore 2>/dev/null || GI_MISSING="$GI_MISSING $pat"
done
if [ -z "$GI_MISSING" ]; then
  pass ".gitignore 覆盖运行态路径"
else
  fail ".gitignore 未覆盖:$GI_MISSING"
fi

# ── 3. 核心测试 ────────────────────────────────────────────────
section "3. 核心测试"

for t in test_init_workspace test_state_path_resolution \
         test_orchestrator_split_smoke test_orchestrator_e2e; do
  if python3 ".harness/tests/$t.py" >/dev/null 2>&1; then
    pass "$t"
  else
    fail "$t 失败（单独运行查看详情: python3 .harness/tests/$t.py）"
  fi
done

# ── 4. 文档一致性 ──────────────────────────────────────────────
section "4. 文档一致性"

if grep -qF 'Quick Start' README.md 2>/dev/null; then
  pass "README 含 Quick Start"
else
  fail "README 缺少 Quick Start"
fi

for d in docs/install.md docs/quickstart.md; do
  if [ -f "$d" ]; then
    pass "$d 存在"
  else
    fail "$d 缺失"
  fi
done

# ── 汇总 ───────────────────────────────────────────────────────
echo
if [ "$FAIL" -eq 0 ]; then
  printf '\033[32m发布前自检通过：全部检查项 OK\033[0m\n'
  exit 0
else
  printf '\033[31m发布前自检失败：%d 项未通过\033[0m\n' "$FAIL"
  exit 1
fi
