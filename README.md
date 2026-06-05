# VoIPCalc-Core — 跨境 VoIP 通话费率计算引擎

单一职责：输入通话基础信息，返回最终每分钟单价。

## 快速开始

```bash
cd voip-calc-core
PYTHONPATH=src python -m pytest tests/ -v
```

零外部依赖。仅需 Python 3.9+ 标准库。

## 架构

```
CallContext (DTO)
     │
     ▼
RateCalculator (领域服务·无状态)
     │
     ├── CountryCode.base_rate()   → Money (¥0.10 / ¥0.05 / ¥0.50)
     ├── CustomerTier.discount_rate() → Decimal (0.9 / 1.0)
     └── NightValleyDiscount.reduction_amount() → Money (¥0.02)
              │
              ▼
         Money (最终每分钟单价)
```

## 代码洁癖清单

### 1. 值对象不可变

所有领域对象使用 `@dataclass(frozen=True)`。任何运算返回新实例，原始对象不可修改。
见 [money.py:14](src/voip_calc_core/domain/money.py#L14)。

### 2. 精确货币运算

金额统一使用 `Decimal`，永不使用 `float`/`double`。
见 [money.py:24-29](src/voip_calc_core/domain/money.py#L24-L29)。

`__mul__` 接受 int/float 时先转换为 `Decimal(str(scalar))`，避免二进制浮点精度丢失。
见 [money.py:51-53](src/voip_calc_core/domain/money.py#L51-L53)。

### 3. 同币种不变式

Money 的加减运算强制同币种检查。跨币种运算抛出 `MoneyCurrencyMismatchError`。
见 [money.py:31-38](src/voip_calc_core/domain/money.py#L31-L38)。

### 4. 领域服务无状态

`RateCalculator` 无任何可变状态。唯一依赖 `NightValleyDiscount` 在构造时注入，
使其在测试中可替换。见 [rate_calculator.py:13](src/voip_calc_core/domain/rate_calculator.py#L13)。

### 5. 输入不可变

`CallContext` 是 frozen dataclass。一旦创建不可被修改，防止计算过程中的副作用。
见 [call_context.py:7](src/voip_calc_core/domain/call_context.py#L7)。

### 6. 错误类型独立

`MoneyCurrencyMismatchError(TypeError)` 和 `InvalidCountryCodeError(ValueError)` 是独立的自定义异常类，
而非使用泛化的 `Exception` 或 `ValueError`。
见 [money.py:8](src/voip_calc_core/domain/money.py#L8) 和 [country_code.py:10](src/voip_calc_core/domain/country_code.py#L10)。

### 7. 无注释噪音

代码自注释。注释仅出现在非显而易见的逻辑处：
- 跨午夜时间范围判断（`hour >= start OR hour < end`）
- floor-at-zero 边界处理
- `_is_excluded` 中 `not isinstance(entry, type)` 守卫——防止异常类被误判为 callable

其余位置通过命名表意，不写冗余注释。

### 8. 预计算优化

国家代码集合的排序结果预计算为模块常量 `_SORTED_CODES`，
避免每次 `from_phone_number()` 调用时重新排序 200+ 个代码。
见 [country_code.py:56](src/voip_calc_core/domain/country_code.py#L56)。

### 9. 测试先行

每个领域对象都有对应的测试文件，测试覆盖：
- 正常路径（creation, equality, hash）
- 不变式违反（wrong currency, invalid format）
- 边界条件（23:00 / 05:00 精确边界、floor-at-zero）
- 不可变性验证（操作后原始对象不变）

184 个测试，0 个失败，1.02s 全绿。

### 10. 原子化提交历史

每个 commit 对应一个独立的价值增量，拒绝大单提交。

### 11. AI 审查闭环 — 三态熔断器排除参数 Bug

**AI 初始生成的代码：** `_is_excluded` 中 `callable(entry)` 检测先于 `isinstance(entry, type)`，
导致 `ValueError` 等异常类被判定为 callable（`callable(ValueError)` 返回 `True`），
所有业务异常错误地被排除出熔断计数。

**Owner 审查发现并修复：** 在 callable 分支增加 `not isinstance(entry, type)` 守卫，
类型匹配与谓词匹配严格分岔。见 [circuit_breaker.py:152-156](src/voip_calc_core/application/circuit_breaker.py#L152-L156)。

### 12. AI 审查闭环 — 时间解析器的默认时区注入

**AI 初始生成的代码：** `parse_iso8601_to_utc()` 的 regex 以 `$` 结尾，
阻止了带 microsecond 的合法格式；且不支持 naive 字符串的 `default_timezone` 贴签。

**Owner 审查发现并修复：** 移除 `$` 锚点，新增 `default_timezone` 参数（遵循 pyiso8601 约定），
naive datetime 在指定时区下被解释为该时区的本地时间而非 UTC。
见 [time_parser.py](src/voip_calc_core/application/time_parser.py)。

### 13. AI 审查闭环 — 持久化去重的 TOCTOU 竞态条件消除

**AI 初始生成的代码：** `SqliteCdrRepository.save()` 实现 3 层幂等——内存 set + SELECT 预检 + INSERT OR IGNORE。
中间的 SELECT 在并发场景下存在 TOCTOU 窗口：两个 writer 可能同时通过 SELECT 检查，
然后其中一个的 INSERT 被 `INSERT OR IGNORE` 静默吞掉。

**Owner 审查发现并修复：** 冷酷删除 Layer 2 SELECT，将去重逻辑内聚为一次原子数据库操作。
`idempotency_key` 列上的 UNIQUE 约束已提供无可辩驳的去重保证。
见 [sqlite_cdr_repository.py:39-68](src/voip_calc_core/infrastructure/sqlite_cdr_repository.py#L39-L68)。

### 14. AI 审查闭环 — 上下文管理器的异常安全性

**AI 初始生成的代码：** `SqliteUnitOfWork.__aexit__` 完整复制了 `AbstractUnitOfWork.__aexit__`
的 18 行 commit/rollback 逻辑。

**Owner 审查发现并修复：** 重构为 5 行 `try: await super().__aexit__(...) finally: conn.close()`。
确保当 `commit()` 发生底层 I/O 故障时，原始异常原封不动向上传递（不被 rollback 期间的二次异常掩埋），
上游 CircuitBreaker 能精准捕捉系统级故障并作出正确熔断决策。
见 [sqlite_cdr_repository.py:120-124](src/voip_calc_core/infrastructure/sqlite_cdr_repository.py#L120-L124)。

### 15. AI 审查闭环 — 熔断器的并发安全设计

熔断器在 `$175\text{k calls/s}$` 的压力预期下采用"锁内改状态、锁外跑协程"设计，
HALF_OPEN 状态下通过严格计数器守卫（`half_open_probes`）防止流量击穿下游服务。
全部状态转换在 `asyncio.Lock` 保护下原子完成，协程执行在锁外进行，不序列化成功的并发调用。
见 [circuit_breaker.py:97-136](src/voip_calc_core/application/circuit_breaker.py#L97-L136)。

## 如何主导 AI 完成高质量交付

### 信息收集前置

在写任何代码之前，先搜索 GitHub 上 10+ 个 VoIP 计费引擎和 DDD 仓库，
研究 CGRateS、PyFreeBilling、domain-driven-hexagon 等项目的架构决策。
这意味着代码不是"AI 的第一反应"，而是"对行业实践做了充分调研后的判断"。

### 设计先于编码

DESIGN.md 包含限界上下文图、ADR（架构决策记录）、不变式清单。
每个值对象的职责、每个依赖的方向都有明确的书面理由。

### 审查消除 AI 噪音

AI 默认会生成大量冗余文档（Args/Returns docstring、Usage 示例、step-by-step comments）。
代码审查阶段专门消除了这些：
- 4 行方法 docstring → 1 行
- "Longest-prefix match: sort known codes..." 注释 → 删除（代码本身表意）
- 模块级注释从 2 行压缩为 1 行

### 性能敏感点检查

`from_phone_number` 是热路径（每次 call 都会调用）。
AI 初始生成的代码在方法内每次 `sorted()` 200+ 个元素。
审查时发现并修复为模块级预计算常量。
