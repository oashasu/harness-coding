#!/usr/bin/env bash
# Harness Coding — 首次安装引导
# 目标：让新用户一条命令装齐依赖并自检，无需手抄命令。
#
# 用法:
#   ./scripts/bootstrap.sh
#
# 完整安装说明见 docs/install.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Harness Coding 引导安装"
echo "    仓库根: $REPO_ROOT"
echo

# 1. 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 未找到 python3，请先安装 Python 3.9+" >&2
  exit 1
fi
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)'; then
  echo "[错误] Python 版本过低：检测到 $PY_VER，要求 3.9+" >&2
  exit 1
fi
echo "==> Python 版本: $PY_VER (要求 3.9+) ✓"

# 2. 安装 Python 依赖
echo "==> 安装 Python 依赖 (requirements.txt)"
python3 -m pip install -r requirements.txt

# 3. 自检依赖可导入
echo "==> 校验依赖可导入"
python3 -c "import jsonschema, yaml; print('    依赖 OK: jsonschema, pyyaml')"

echo
echo "==> 完成。下一步："
echo "    1. 在你的项目目录下初始化工作区："
echo "       python3 $REPO_ROOT/.harness/scripts/init-workspace.py --workspace ."
echo "    2. 运行第一个验证命令（详见 docs/quickstart.md）："
echo "       python3 $REPO_ROOT/.harness/scripts/preflight.py \\"
echo "         --stage REQ_DRAFT --state-file .harness/state/harness-state.json"
