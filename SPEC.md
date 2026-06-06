# VoIP-Calc-Core — 形式化规格

本文档定义每个公共函数的**契约**：前置条件（输入约束）、后置条件（输出保证）、不变量（始终成立的跨函数规则）。所有测试用例均从此文档推导，所有实现变更必须满足此契约。

## 记法约定

| 符号 | 含义 |
|---|---|
| $R_{base}(cc)$ | 国家码 `cc` 的基础费率（¥/分钟） |
| $D(tier)$ | 客户等级折扣因子 |
| $N(t, h)$ | 夜间减免适用判定：`true` 当时间 $t$ 处于 $h$ 定义的夜间窗口 |
| $R(t, cc, tier)$ | 最终每分钟单价 |
| $C(t, cc, tier, d, b)$ | 总话费 = $R \times$ 计费分钟数，舍入到分 |
| $\lceil x \rceil$ | 向上取整（ceiling） |
| $[a, b)$ | 左闭右开区间 |

---

## 1. Money — 货币值对象

### 1.1 构造

```
Money(amount, currency)
  前置: amount 为 Decimal 或可安全转换为 Decimal 的类型
        若 amount 为 float，走 Decimal(str(amount)) 间接转换
  后置: self.amount 始终为 Decimal 类型
        self.currency 不变
```

### 1.2 加法

```
a + b
  前置: a.currency == b.currency
  后置: result.amount == a.amount + b.amount
        result.currency == a.currency
  异常: MoneyCurrencyMismatchError 若币种不一致
```

### 1.3 减法

```
a - b
  前置: a.currency == b.currency
  后置: result.amount == a.amount - b.amount
        result.amount 可为负数
        result.currency == a.currency
  异常: MoneyCurrencyMismatchError 若币种不一致
```

### 1.4 标量乘法

```
money * scalar
  前置: scalar ∈ {Decimal, int, float}
        若 scalar 为 int: scalar → Decimal(scalar)
        若 scalar 为 float: scalar → Decimal(str(scalar))  (IEEE 754 防御)
  后置: result.amount == self.amount * scalar_as_Decimal
        result.currency == self.currency
```

### 1.5 下限保护

```
money.at_least(floor)
  前置: money.currency == floor.currency
  后置: result == money      若 money.amount >= floor.amount
        result == floor      若 money.amount < floor.amount
```

### 1.6 分位舍入

```
money.round_to_cents()
  后置: result.amount == quantize(self.amount, 0.01, ROUND_HALF_UP)
        result.currency == self.currency
  幂等: result.round_to_cents() == result
```

---

## 2. CountryCode — 国家码值对象

### 2.1 构造

```
CountryCode(code)
  前置: code 匹配 r"^\+\d+$"  (以 + 开头，后接至少一位数字)
  后置: self.code == code
  异常: InvalidCountryCodeError 若格式不合法
```

### 2.2 基础费率查询

```
cc.base_rate()
  后置: result 为 Money 类型，币种为 CNY
        result.amount == R_base(cc.code)  其中:
          R_base("+86") == 0.10
          R_base("+1")  == 0.05
          R_base(other) == 0.50  (默认)
```

### 2.3 从号码提取

```
CountryCode.from_phone_number(phone)
  前置: phone 以 "+" 开头
  后置: 返回 CountryCode 实例，其 code 为 phone 的最长匹配国家前缀
        匹配策略:
          1. Trie 最长前缀匹配 (已知国家码集合)
          2. 正则回退 r"^\+(\d{1,3})"  (未知道国家码)
  异常: InvalidCountryCodeError 若无法提取
```

---

## 3. CustomerTier — 客户等级

### 3.1 折扣率

```
tier.discount_rate()
  后置: D(VIP)    == 0.9
        D(NORMAL) == 1.0
  不变量: 对所有 TierEnum 成员, 0 < D(tier) <= 1.0
```

---

## 4. CallContext — 通话上下文

### 4.1 构造

```
CallContext(caller, callee, call_time)
  前置: call_time.tzinfo is not None  (必须时区感知)
  后置: 字段不可变 (frozen dataclass)
  异常: ValueError 若 call_time 为 naive datetime
```

---

## 5. Duration — 通话时长

### 5.1 构造

```
Duration(seconds)
  前置: seconds >= 0
  后置: self.seconds == seconds
  异常: ValueError 若 seconds < 0
```

---

## 6. NightValleyDiscount — 夜间减免

### 6.1 构造

```
NightValleyDiscount(start_hour, end_hour, reduction, charging_timezone)
  前置: 0 <= start_hour <= 23
        0 <= end_hour <= 23
        reduction >= 0
  后置: 字段不可变 (frozen dataclass)
  默认: start_hour=23, end_hour=5, reduction=0.02, charging_timezone=UTC+8
  异常: ValueError 若小时或减免值不合法
```

### 6.2 减免适用判定

```
nv.is_applicable(call_time)
  前置: call_time.tzinfo is not None
  后置: 将 call_time 归一化到 charging_timezone 后:
        若 start_hour > end_hour (跨午夜):
          result == (hour >= start_hour OR hour < end_hour)
        若 start_hour <= end_hour (同日):
          result == (start_hour <= hour < end_hour)
  边界: start_hour 时刻 → true; end_hour 时刻 → false (半开区间)
  不变量: is_applicable 的结果仅取决于 call_time 在 charging_timezone 中的小时数
```

### 6.3 减免金额

```
nv.reduction_amount()
  后置: result == Money(nv.reduction, CNY)
```

---

## 7. BillingIncrement — 计费粒度

### 7.1 构造

```
BillingIncrement(initial_seconds, subsequent_seconds)
  前置: initial_seconds >= 1
        subsequent_seconds >= 1
  后置: 字段不可变 (frozen dataclass)
  预置常量:
    PER_MINUTE     = BillingIncrement(60, 60)
    PER_6_SECONDS  = BillingIncrement(6, 6)
    PER_SECOND     = BillingIncrement(1, 1)
```

### 7.2 计费时长转换

```
billing.chargeable_duration(actual_seconds)
  前置: 无 (actual_seconds 可为任意整数)
  后置: 若 actual_seconds <= 0:
          result == 0
        若 0 < actual_seconds <= initial_seconds:
          result == initial_seconds  (首段保底)
        若 actual_seconds > initial_seconds:
          result == initial_seconds + k * subsequent_seconds
          其中 k = ceil((actual_seconds - initial_seconds) / subsequent_seconds)
  
  复杂度: O(1) 整数算术
  不变量: result >= actual_seconds  (ceiling 语义)
         result - initial_seconds ≡ 0 (mod subsequent_seconds)  当 result > initial_seconds
```

---

## 8. RateCalculator — 费率计算（领域服务，无状态）

### 8.1 每分钟单价

```
calculator.calculate(context, customer_tier)
  前置: context.callee 以 "+" 开头
        context.call_time.tzinfo is not None
  后置: R(t, cc, tier) = max(0, R_base(cc) * D(tier) - reduction)
        其中 reduction = 0.02 若 N(t, h)=true, 否则 0
  
  不变量:
    (1) result.amount >= 0  — 零值下限
    (2) result.currency == CNY
    (3) R(t, cc, VIP) <= R(t, cc, NORMAL)  — VIP 永不比 NORMAL 贵
    (4) 若 N(t, h)=true:  R(t, cc, tier) <= R(t_noon, cc, tier)  — 夜间不高于白天
  
  纯函数: 对相同输入，重复调用返回相同结果(值相等，非引用相等)
  无副作用: 不读写外部状态，不执行 IO
```

### 8.2 总话费

```
calculator.calculate_charge(context, customer_tier, duration, billing=None)
  前置: duration.seconds >= 0
        billing 默认为 BillingIncrement.PER_MINUTE
  后置: 1. per_minute_rate = calculate(context, customer_tier)
        2. chargeable_seconds = billing.chargeable_duration(duration.seconds)
        3. chargeable_minutes = chargeable_seconds / 60  (Decimal 除法)
        4. raw_charge = per_minute_rate * chargeable_minutes
        5. result = raw_charge.round_to_cents()  (ROUND_HALF_UP)
  
  不变量:
    (1) result.amount >= 0
    (2) calculate_charge(context, tier, Duration(0), billing) == Money(0, CNY)
    (3) 对任一 billing: calculate_charge(context, tier, d1) <= calculate_charge(context, tier, d2)
        当 d1.seconds <= d2.seconds  (单调递增)
```

---

## 9. parse_iso8601_to_utc — 时间解析

```
parse_iso8601_to_utc(raw, *, field_name, default_timezone)
  前置: raw 为非空非空白字符串
  后置: result.tzinfo == timezone.utc
        解析支持:
          - 标准 ISO-8601 (如 "2026-06-05T14:30:00+08:00")
          - Z/z 后缀 (归一化为 +00:00)
          - 无冒号偏移 (如 "+0800" → "+08:00")
          - naive datetime + default_timezone (若提供)
  
  异常: ValueError:
        - 若 raw 为空/空白 (使用 field_name 标识字段)
        - 若 raw 格式不合法
        - 若 raw 为 naive datetime 且 default_timezone 为 None
  
  不变量: 相同输入 → 相同输出 (确定性)
```

---

## 10. RoutingAppService.execute — 应用层编排

```
service.execute(request)
  前置: request.caller, callee, call_start_time, idempotency_key 均非空
        request.call_start_time 为合法 ISO-8601 字符串
  
  管道 (5 步):
    1. parse_iso8601_to_utc(request.call_start_time) → call_time
    2. _fetch_tier_safely(request.caller) → tier
       若 fetcher 不可用或断路器开路 → CustomerTier(NORMAL) (降级)
    3. CallContext(caller, callee, call_time) → ctx
    4. calculator.calculate(ctx, tier) → money
       calculator.is_night_valley(call_time) → night_valley
    5. 若提供了 UoW factory:
          RatedCall.create(...) → rated_call
          uow.cdr_repo.save(rated_call)
          uow.commit()
  
  后置: response.amount >= 0
        response.currency == "CNY"
        response.tier ∈ {"VIP", "NORMAL"}
  
  降级策略: 任何外部依赖故障 → tier 回退为 NORMAL，不抛异常
  幂等: 同 idempotency_key 的两次调用 → 仅保存一次 CDR (DB UNIQUE + 内存去重)
```

---

## 11. 跨模块不变量

### 11.1 精度安全

```
所有货币运算使用 Decimal，禁止 float 直接参与乘法或除法。
唯一允许 float 的路径: Money.__mul__ 中 Decimal(str(float)) 防御转换。
```

### 11.2 时区确定性

```
夜间时段判定仅依赖 charging_timezone (默认 UTC+8)。
不依赖系统时区、环境变量、或 datetime.now() 的本地时间。
CallContext 拒绝 naive datetime。
```

### 11.3 不可变性

```
所有领域值对象均为 @dataclass(frozen=True)。
任何修改操作返回新实例，不改变原实例。
```

### 11.4 零依赖

```
标准库 only。不依赖 Django, SQLAlchemy, requests, pytz, zoneinfo (Python 3.9)。
时区通过 datetime.timezone(datetime.timedelta(hours=8)) 构造。
```

---

## 12. 测试推导

每条后置条件 → 至少一个测试类。每条不变量 → 至少一个 property test。

| 规格条目 | 测试覆盖 |
|---|---|
| 8.1 不变量(1): rate >= 0 | `TestRateCalculatorProperties::test_rate_never_negative` |
| 8.1 不变量(3): VIP <= NORMAL | `TestRateCalculatorProperties::test_vip_never_exceeds_normal` |
| 8.1 不变量(4): night <= day | `TestRateCalculatorProperties::test_night_rate_never_exceeds_day_rate` |
| 8.2 不变量(3): 单调递增 | `TestRateCalculatorProperties::test_charge_grows_with_duration` |
| 7.2 不变量: ceiling | `TestBillingIncrementProperties::test_chargeable_never_less_than_actual` |
| 7.2 不变量: 模约束 | `TestBillingIncrementProperties::test_chargeable_is_multiple_of_subsequent` |
| 6.2 不变量: 小时判定 | `TestNightValleyProperties::test_applicable_only_in_window` |
| 6.2 边界: 半开区间 | `TestNightValleyProperties::test_cross_midnight_or_same_day_consistent` |
| 1.6 幂等: round_to_cents | `TestMoneyProperties::test_round_trip_via_cents` |
| 1.5 下限: at_least | `TestMoneyProperties::test_floor_protection` |
| 5.1 负值拒绝 | `TestDurationProperties::test_negative_duration_rejected` |
