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

本上下文职责单一：给定一次通话的基础信息，计算出最终每分钟单价，
并原子持久化 CDR（Call Detail Record）审计记录。
不涉及路由、不涉及账户余额扣减。

## 2. 领域模型 (Domain Model)

### 2.1 Money — 金额值对象

```
Money { amount: Decimal, currency: str }
```

- 不可变。所有运算返回新实例。
- 同币种不变式：加减运算必须在同币种间进行，否则抛出 MoneyCurrencyMismatchError。
- 乘法允许与标量（Decimal/int/float）相乘，用于折扣计算。
- 减法结果若为负数，由调用方决定是否截断为 0（非 Money 自身职责）。

决策权衡：Decimal 是唯一可接受的表示——float 在累加折扣和减免时精度不可预测，int（分为单位）在国内场景尚可但在多币种跨境场景下因各币种精度不一而崩溃。`__mul__` 接受 int/float 时强制 `Decimal(str(scalar))` 转换，拒绝隐式二进制浮点混入。

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

决策权衡：国家代码与基础费率的绑定是刻意耦合——费率表从业务视角天然以国家为维度划分，拆成独立配置表只是增加一层间接且引入配置漂移风险。`from_phone_number()` 使用 E.164 全集进行最长前缀匹配，而非前 N 位硬编码推断——1-3 位变长国家代码下，简单前缀匹配会错误地将 +44 呼叫误判为 +442 或反之。

### 2.3 CustomerTier — 客户身份值对象

```
CustomerTier { tier: TierEnum }
TierEnum { VIP, NORMAL }
```

- 封装客户身份等级。
- 关联折扣率：discount_rate() -> Decimal
  - VIP    → 0.9 (9折)
  - NORMAL → 1.0 (无折扣)

决策权衡：`CustomerTier` 作为独立参数传入 `calculateRate()`，而非作为 `CallContext` 字段。原因是 tier 由外部账户系统（CustomerProfileFetcher 端口）反查得出，不是通话本身的属性。将其塞入 CallContext 会模糊应用层（反查与降级）和领域层（纯计算）之间的边界，导致测试时需要构造假账户数据来满足 CallContext。

### 2.4 NightValleyDiscount — 夜间低谷折扣值对象

```
NightValleyDiscount { start_hour: int, end_hour: int, reduction: Money }
```

- 封装夜间时段定义与减免金额。
- 检查给定时间是否在时段内：is_applicable(call_time: datetime) -> bool
- 夜间定义：23:00 ~ 次日 05:00
- 减免金额：¥0.02/分钟

决策权衡：时段检测逻辑内聚在值对象内部，`RateCalculator` 只问"是否适用"——这消除了计算流程中的 if-else 分支。跨午夜时段判断（`hour >= 23 or hour < 5`）而非简单的区间比较，这在本对象内处理，不泄露到调用方。`NightValleyDiscount` 作为可注入依赖传入 `RateCalculator.__init__`，测试可替换自定义折扣策略（如 floor-at-zero 边界场景），而生产代码保持默认零配置。

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

决策权衡：`frozen=True` 不可变——通话上下文一旦创建不可被计算链上任何环节修改，防止副作用。输入模型与计算逻辑解耦：未来 `CallContext` 扩展（如 `call_duration`、`quality_score`）不影响 `RateCalculator` 接口，反之亦然。

### 2.6 Duration — 通话时长值对象

```
Duration { seconds: int }
```

- 不可变。封装通话时长，单位秒。
- 非负校验：构造时拒绝负值。

### 2.7 BillingIncrement — 计费增量值对象

```
BillingIncrement { initial_seconds: int, subsequent_seconds: int }
```

- 不可变。将实际通话时长转换为计费时长（电信行业 ceiling 语义）。
- 常用模式：60/60（整分钟舍入）、6/6（6秒脉冲）、1/1（逐秒计费）、30/6（首30秒 + 6秒脉冲）。
- O(1) 整数运算，无循环。

### 2.8 RateCalculator — 费率计算器 (领域服务)

```
RateCalculator:
    calculateRate(context: CallContext, tier: CustomerTier) -> Money
    calculate_charge(context, tier, duration, billing=None) -> Money
```

- 纯粹、无状态、无副作用。
- 四步管道：
  1. 从 callee 提取 CountryCode → 查基础费率
  2. 接收 CustomerTier → 应用折扣率
  3. 检查 call_time 是否在夜间低谷 → 减免固定金额
  4. 出口守卫 → at_least(¥0.00)

决策权衡：当前 3 条规则使用硬编码管道而非策略模式——策略模式在 3 条规则规模下是过度设计，增加抽象层级却无实际收益。ADR-3 明确约定：规则增至 5+ 条时重构为 `Pipeline<Rule>`。出口守卫 `at_least(Money.zero())` 是最后防线——三条规则叠加后可能出现负值（如极端的折扣 + 减免场景），必须硬截断为 ¥0.00，这是一个不可商量的不变式。

## 3. 架构决策记录 (ADR)

### ADR-1: 纯领域模型，零框架依赖

核心逻辑不依赖任何框架。测试可直接实例化值对象和领域服务，无需 mock。

### ADR-2: Python + Decimal 精确运算

Python 3.9+。Decimal 类型避免浮点精度丢失。不使用 float 表示金额。

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
│       ├── country_code.py       # CountryCode 值对象 + Trie
│       ├── customer_tier.py      # CustomerTier 值对象
│       ├── night_valley.py       # NightValleyDiscount 值对象
│       ├── call_context.py       # CallContext DTO
│       ├── duration.py           # Duration 值对象
│       ├── billing_increment.py  # BillingIncrement 值对象
│       └── rate_calculator.py    # RateCalculator 领域服务
│   └── application/
│       ├── __init__.py
│       ├── dto.py                # Request/Response DTO
│       ├── ports.py              # CustomerProfileFetcher / CdrRepository / UoW
│       ├── rated_call.py         # RatedCall PO (持久化数据对象)
│       ├── time_parser.py        # ISO-8601 严格解析
│       ├── circuit_breaker.py    # 熔断器状态机
│       └── routing_service.py   # RoutingAppService 编排 (5步管道)
│   └── infrastructure/
│       ├── __init__.py
│       └── sqlite_cdr_repository.py  # SQLite 持久化适配器
├── tests/
│   ├── __init__.py
│   ├── test_money.py
│   ├── test_country_code.py
│   ├── test_customer_tier.py
│   ├── test_night_valley.py
│   ├── test_rate_calculator.py
│   ├── test_duration.py
│   ├── test_billing_increment.py
│   ├── test_properties.py        # 属性测试 (Hypothesis)
│   ├── mutate.py                 # 变异测试
│   ├── test_time_parser.py
│   ├── test_circuit_breaker.py
│   ├── test_application_dto.py
│   ├── test_routing_service.py
│   ├── test_rated_call.py
│   ├── test_cdr_repository.py
│   └── test_sqlite_cdr_repository.py
├── DESIGN.md
├── APPLICATION_DESIGN.md
├── PERSISTENCE_DESIGN.md
├── SPEC.md
├── PROMPTS.md
└── README.md
```
