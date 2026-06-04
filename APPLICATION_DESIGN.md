# APPLICATION_DESIGN.md — 应用层服务设计

## 1. 职责边界与依赖流向

```
┌────────────────────────────────────────────────────────────────┐
│                    Application Layer (应用层)                   │
│                                                                │
│   Incoming Request  ┌─────────────────────┐                    │
│  ──────────────────▶│  RoutingAppService  │                    │
│    (Raw DTO)        │     (应用服务)       │                    │
│                     └──────────┬──────────┘                    │
│                                │                               │
│                     ┌──────────┼──────────┐                    │
│                     ▼          ▼          ▼                    │
│              time_parser   ports.py   circuit_breaker          │
│              (ISO-8601)   (Fetcher)   (熔断器)                 │
│                                                                │
└────────────────────────────────┼───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│                     Domain Layer (领域层)                       │
│                                                                │
│                     ┌─────────────────────┐                    │
│                     │   RateCalculator    │                    │
│                     │     (领域服务)       │                    │
│                     └─────────────────────┘                    │
└────────────────────────────────────────────────────────────────┘
```

**RoutingAppService** 是无状态应用服务。不包含费率计算规则，只做：
- 外部协议 → 领域模型的翻译
- 外部上下文集成（账户系统反查）
- 降级策略（熔断 + 兜底）
- 响应封装（含审计元数据）

## 2. 外部端口 (Hexagonal Ports)

### CustomerProfileFetcher

```python
from abc import ABC, abstractmethod

class CustomerProfileFetcher(ABC):
    @abstractmethod
    async def fetch_tier_by_phone(self, phone_number: str) -> CustomerTier:
        ...
```

- 适配器**只负责成功或抛异常**，不做降级
- 降级逻辑统一在 `RoutingAppService._fetch_tier_safely()` 中：
  - 熔断器 OPEN → 直接返回 `NORMAL`（不调用适配器）
  - 适配器抛异常 → 捕获后返回 `NORMAL`
- 生产实现：Redis 缓存 → gRPC 账户服务
- 测试实现：内存 dict 映射

## 3. 入参/出参契约

### CalculateRateRequest

```python
@dataclass(frozen=True)
class CalculateRateRequest:
    caller: str                  # +8613800000001
    callee: str                  # +14150000000
    call_start_time: str         # "2026-06-05T14:30:00+08:00"
    idempotency_key: str         # 防重复计价
```

- `call_start_time` 保持 ISO-8601 字符串，避免框架层隐式反序列化绕过 CallContext 的时区校验
- 四个字段均验证非空（含空白字符串拒绝）

### CalculateRateResponse

```python
@dataclass(frozen=True)
class CalculateRateResponse:
    amount: Decimal              # 0.045
    currency: str                # "CNY"
    country_code: str            # "+1"
    tier: str                    # "VIP"
    night_valley_applied: bool   # False
    idempotency_key: str         # 回显请求幂等键
```

审计字段 (`country_code`, `tier`, `night_valley_applied`) 让调用方能追溯费率的组成原因。

## 4. 四步管道

```
call_start_time ──►[1] parse_iso8601_to_utc()──► aware UTC datetime
                                                       │
caller ──►[2] breaker.call(fetch_tier)──► VIP/NORMAL ◄─┤ (降级: NORMAL)
                                                       │
callee ──►[3] CallContext(caller, callee, time)────────┤
                                                       │
         ──►[4] RateCalculator.calculate(ctx, tier)────┤
                                                       │
         ──►[5] CalculateRateResponse(...) ◄────────────┘
```

每一步的防御策略：

| 步骤 | 防御措施 |
|------|----------|
| 1. 时间解析 | 拒绝 naive 字符串，Py3.9 `Z`/`±HHMM` 预处理，统一归一化 UTC |
| 2. 身份反查 | 熔断器阻止雪崩，异常降级 NORMAL |
| 3. 领域构造 | CallContext 自身校验时区感知 |
| 4. 费率计算 | 出口守卫 `at_least(¥0)` 防止负数单价 |
| 5. 响应封装 | 不回显原始号码（已由 CallContext 持有） |

## 5. 熔断器 (Circuit Breaker)

```python
class CircuitBreaker:
    CLOSED     # 正常：统计连续失败，达到阈值 → OPEN
    OPEN       # 熔断：直接拒绝（或返回 fallback），等待 recovery_timeout
    HALF_OPEN  # 试探：允许 limited probes，成功 → CLOSED，失败 → OPEN
```

- 零外部依赖，纯 `asyncio.Lock` 保证协程安全
- 协程执行在锁外进行，不序列化成功的并发调用
- 可配置：`failure_threshold`（默认 5）、`recovery_timeout`（默认 30s）、`half_open_probes`（默认 1）

## 6. 架构决策

### 降级策略的所有权

降级 `NORMAL` 的逻辑放在 `RoutingAppService._fetch_tier_safely()`，不放在各个 `CustomerProfileFetcher` 实现中。原因：
- 降级是**应用层策略决策**，不是适配器职责
- 每个适配器写一遍降级 = 代码重复 + 行为不一致风险
- 适配器只负责"成功或抛异常"，单一职责

### 幂等键

`idempotency_key` 目前作为请求字段透传并回显。未来持久化层应基于此键做去重（`UNIQUE` 约束 + `ON CONFLICT` 返回已有结果）。

### 零框架依赖

应用层与领域层一致：`import` 全部来自 Python 标准库。测试也无需 mock 框架（`unittest.mock.AsyncMock` 仅在测试中使用，不在生产代码路径中）。

## 7. 目录结构

```
voip-calc-core/
├── src/voip_calc_core/
│   ├── __init__.py
│   ├── domain/
│   │   ├── money.py
│   │   ├── country_code.py
│   │   ├── customer_tier.py
│   │   ├── night_valley.py
│   │   ├── call_context.py
│   │   └── rate_calculator.py
│   └── application/                          # NEW
│       ├── __init__.py
│       ├── dto.py
│       ├── ports.py
│       ├── time_parser.py
│       ├── circuit_breaker.py
│       └── routing_service.py
├── tests/
│   ├── test_money.py
│   ├── test_country_code.py
│   ├── test_customer_tier.py
│   ├── test_night_valley.py
│   ├── test_rate_calculator.py
│   ├── test_time_parser.py                   # NEW
│   ├── test_circuit_breaker.py               # NEW
│   ├── test_application_dto.py               # NEW
│   └── test_routing_service.py               # NEW
├── DESIGN.md
├── APPLICATION_DESIGN.md                     # NEW (this file)
├── PROMPTS.md
└── README.md
```
