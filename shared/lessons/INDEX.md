# 偏航经验库

> Harness Coding v2.0.0 — 从失败中学习，避免重复踩坑

## 目录结构

```
shared/lessons/
├── INDEX.md              # 本文件 — 全局索引
├── by-domain/            # 按业务域索引
│   ├── payment.md        # 支付域教训
│   ├── order.md          # 订单域教训
│   └── ...
├── by-type/              # 按错误类型索引
│   ├── sql-error.md      # SQL 相关错误
│   ├── null-safety.md    # 空指针相关
│   └── ...
└── lifecycle/            # 生命周期管理
    ├── active.md         # 活跃教训（自动注入新任务）
    └── archived.md       # 已归档教训（不再注入）
```

## 偏航记录格式

每条 lesson 存储为独立 JSON 文件，路径：`shared/lessons/data/<lesson_id>.json`

```json
{
  "lesson_id": "L-001",
  "task_id": "T-001",
  "domain": "payment",
  "error_type": "sql-injection",
  "severity": "critical",
  "title": "MyBatis ${} 导致 SQL 注入",
  "description": "在退款查询中使用 ${orderNo} 拼接 SQL，攻击者可注入恶意条件",
  "root_cause": "模板中误用 ${} 而非 #{}",
  "fix_approach": "将 ${} 替换为 #{}，参数化查询",
  "prevention": "Tier 1 check-sql-injection.py 自动检测",
  "confidence": 0.95,
  "tags": ["sql", "mybatis", "security"],
  "created_at": "2026-06-07T00:00:00Z",
  "status": "active",
  "injected_count": 0
}
```

## 自动注入逻辑

新任务开始时，lesson-manager 会：
1. 根据任务的 domain 和 error_type 匹配相关 lesson
2. 按 confidence 降序排列
3. 最多注入 10 条（避免信息过载）
4. 注入到 Spec 的 "已知风险" 区块
