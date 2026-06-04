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

69 个测试，0 个失败。

### 10. 原子化提交历史

6 个 commit，每个对应一个独立的价值增量：

```
cbe4c11 feat(money): add immutable Money value object
629a921 feat(country-code): add CountryCode value object
d7b0141 feat(customer-tier): add CustomerTier value object
b226216 feat(night-valley): add NightValleyDiscount value object
514bf69 feat(country-code): add from_phone_number parsing
c7f06ca feat(rate-calculator): add CallContext and RateCalculator
35983f7 refactor: pre-compute sorted codes, trim docstring noise
```

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
