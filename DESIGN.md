# DESIGN.md — VoIPCalc-Core 领域驱动设计分析

## 1. 限界上下文 (Bounded Context)

```
┌─────────────────────────────────────────────┐
│         VoIPCalc-Core (费率计算上下文)        │
│                                             │
│  ┌──────────┐   ┌──────────────────────┐   │
│  │ CallContext│──▶│  RateCalculator      │   │
│  │ (输入 DTO) │   │  (领域服务·无状态)    │   │
│  └──────────┘   └──────┬───────────────┘   │
│                        │                    │
│         ┌──────────────┼──────────────┐     │
│         ▼              ▼              ▼     │
│  ┌────────────┐ ┌────────────┐ ┌────────┐ │
│  │CountryCode │ │CustomerTier│ │Night   │ │
│  │(值对象)    │ │(值对象)    │ │Valley  │ │
│  │            │ │            │ │(值对象) │ │
│  └────────────┘ └────────────┘ └────────┘ │
│                        │                    │
│                        ▼                    │
│                 ┌──────────┐               │
│                 │  Money   │               │
│                 │ (值对象)  │               │
│                 └──────────┘               │
└─────────────────────────────────────────────┘
```

本上下文职责单一：给定一次通话的基础信息，计算出最终每分钟单价。
不涉及路由、不涉及 CDR 持久化、不涉及账户余额扣减。

## 2. 领域模型 (Domain Model)

### 2.1 Money — 金额值对象

```
Money { amount: Decimal, currency: str }
```

- 不可变。所有运算返回新实例。
- 同币种不变式：加减运算必须在同币种间进行，否则抛出 MoneyCurrencyMismatchError。
- 乘法允许与标量（Decimal/int/float）相乘，用于折扣计算。
- 减法结果若为负数，由调用方决定是否截断为 0（非 Money 自身职责）。

选择理由：消除原始类型迷恋（Primitive Obsession）。Decimal 而非 float 保证精度。

### 2.2 CountryCode — 国家代码值对象

```
CountryCode { code: str }
```

- 封装国家代码（"+86", "+1" 等）。
- 关联基础费率查询：base_rate() -> Money
- 基础费率映射：
  - "+86" (中国) → ¥0.10/分钟
  - "+1"  (美国) → ¥0.05/分钟
  - 其他   → ¥0.50/分钟（默认）

选择理由：将国家代码与费率知识绑定，避免散落在计算逻辑中的 if-else。

### 2.3 CustomerTier — 客户身份值对象

```
CustomerTier { tier: TierEnum }
TierEnum { VIP, NORMAL }
```

- 封装客户身份等级。
- 关联折扣率：discount_rate() -> Decimal
  - VIP    → 0.9 (9折)
  - NORMAL → 1.0 (无折扣)

选择理由：折扣率是 CustomerTier 的内在知识，不是外部注入的配置。

### 2.4 NightValleyDiscount — 夜间低谷折扣值对象

```
NightValleyDiscount { start_hour: int, end_hour: int, reduction: Money }
```

- 封装夜间时段定义与减免金额。
- 检查给定时间是否在时段内：is_applicable(call_time: datetime) -> bool
- 夜间定义：23:00 ~ 次日 05:00
- 减免金额：¥0.02/分钟

选择理由：时段逻辑内聚在值对象内部，RateCalculator 只问"是否适用"。

### 2.5 CallContext — 通话上下文 (输入 DTO)

```
CallContext {
    caller: str,        # 主叫号码
    callee: str,        # 被叫号码
    call_time: datetime  # 通话发起时间
}
```

- 不可变数据传输对象。
- callee 前缀用于提取国家代码。

选择理由：输入模型与计算逻辑解耦。未来扩展（如添加 call_duration）不影响领域服务接口。

### 2.6 RateCalculator — 费率计算器 (领域服务)

```
RateCalculator:
    calculate(context: CallContext, tier: CustomerTier) -> Money
```

- 纯粹、无状态、无副作用。
- 四步管道：
  1. 从 callee 提取 CountryCode → 查基础费率
  2. 接收 CustomerTier → 应用折扣率
  3. 检查 call_time 是否在夜间低谷 → 减免固定金额
  4. 出口守卫 → at_least(¥0.00)

选择理由：费率计算需要跨多个值对象协调，是领域服务（非实体或值对象）的经典场景。

## 3. 架构决策记录 (ADR)

### ADR-1: 纯领域模型，零框架依赖

核心逻辑不依赖任何框架。测试可直接实例化值对象和领域服务，无需 mock。

### ADR-2: Python + Decimal 精确运算

Python 3.10+。Decimal 类型避免浮点精度丢失。不使用 float 表示金额。

### ADR-3: 三层规则叠加而非策略模式

当前仅 3 条规则，使用策略模式属于过度设计。若规则增至 5+ 条，可重构为 Pipeline<Rule>。

### ADR-4: 主叫号码推断客户身份的逻辑放在适配层

从 caller 字符串推断 CustomerTier（如根据号码前缀判断）属于外部集成逻辑，
不放在领域服务内。RateCalculator 接收已解析的 CustomerTier。

## 4. 不变式清单

| 编号 | 不变式 | 实施位置 |
|------|--------|----------|
| I-1 | Money 同币种加减 | Money.__add__ / __sub__ |
| I-2 | 最终费率 >= ¥0.00 | RateCalculator.calculate |
| I-3 | 折扣率在 0~1 之间 | CustomerTier 构造时校验 |
| I-4 | 国家代码格式 +NN | CountryCode 构造时校验 |
| I-5 | CallContext 不可变 | 使用 @dataclass(frozen=True) |

## 5. 目录结构

```
voip-calc-core/
├── src/voip_calc_core/
│   ├── __init__.py
│   └── domain/
│       ├── __init__.py
│       ├── money.py              # Money 值对象
│       ├── country_code.py       # CountryCode 值对象
│       ├── customer_tier.py      # CustomerTier 值对象
│       ├── night_valley.py       # NightValleyDiscount 值对象
│       ├── call_context.py       # CallContext DTO
│       └── rate_calculator.py    # RateCalculator 领域服务
├── tests/
│   ├── __init__.py
│   ├── test_money.py
│   ├── test_country_code.py
│   ├── test_customer_tier.py
│   ├── test_night_valley.py
│   ├── test_call_context.py
│   └── test_rate_calculator.py
├── DESIGN.md
├── PROMPTS.md
└── README.md
```
