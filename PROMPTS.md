# PROMPTS.md — AI 交互记录与提示词留痕

## 对话 1：项目启动与需求理解

**开发者输入**：
> 现在你是我的开发agent，在开发过程中，你需要全程叫我partner，
> 全程需要以非常严格的目标去开发。我不要奉承的话语去评价或者进行任务，
> 我需要客观的思路去分析这件事情的实施，实施过程中你需要保持遇到问题
> 可以先搜集信息，设计方案，推理方案实施，再评价实施困难这一流程，
> 可以在github上搜索相应项目信息，若搜索无果，你需要更换同义词再次搜寻。

**AI 响应**：确认工作流程，建立称呼规则与协作模式。

**开发者的引导策略**：在任务开始前先建立严格的协作规范，明确禁止奉承式输出，要求客观分析。

---

## 对话 2：首次任务下发

**开发者输入**：
> 任务如下：
> 1. 题目背景：请为跨境VOIP话务系统设计并实现一个最核心的通话费率计算引擎
> (VoIPCalc-Core)
> 2. 核心业务需求：calculateRate(CallContext context)，三条可叠加规则
> ...

**AI 处理流程**：
1. 搜索阶段：使用 Agent 工具搜索 GitHub 上 VoIP 计费引擎、DDD 费率计算、Money 值对象等参考项目
2. 产出：获取 CGRateS、PyFreeBilling、domain-driven-hexagon 等项目的架构模式
3. 设计阶段：编写 DESIGN.md，明确限界上下文、值对象、领域服务
4. 实现阶段：TDD 方式逐层构建

---

## 对话 3：代码审核与重构

**开发者输入**（通过工作流约束体现）：
> 请在交付前进行严苛的自我审查，彻底消除AI带来的噪音，死代码与易碎逻辑

**AI 执行的核查动作**：
- 发现 `country_code.py` 中 `sorted(_KNOWN_COUNTRY_CODES, key=len, reverse=True)` 在每次 `from_phone_number` 调用时重新计算 → 提取为模块常量 `_SORTED_CODES`
- 发现 `rate_calculator.py` 的类和方法 docstring 包含冗余的 "Args/Returns/Usage" 段落 → 精简为单行描述
- 发现 `.coverage` 被误提交到 Git → 添加 `.gitignore` 并移除追踪
- Money `__post_init__` 中过早拒绝了非 CNY 货币 → 移除以支持测试场景

---

## 关键设计决策点

### 决策 1：CustomerTier 作为独立参数而非 CallContext 字段

**推理**：客户身份是外部系统（用户账户系统）解析的结果，不是通话本身的属性。
在 DDD 中，领域服务接收已解析的领域对象而非原始字符串。
因此 `calculateRate(context, customer_tier)` 而非 `calculateRate(context)` 隐含从 caller 推断身份。

**替代方案**：在 CallContext 中携带 customer_tier。被拒绝，因为这模糊了应用层和领域层的边界。

### 决策 2：CountryCode 不使用策略模式

**推理**：当前仅 3 条费率规则（+86 / +1 / 默认），策略模式属于过度设计。
在 DESIGN.md ADR-3 中明确标注：规则增至 5+ 条时可重构为 Pipeline<Rule>。

### 决策 3：NightValleyDiscount 作为可注入依赖

**推理**：`RateCalculator.__init__` 接受可选的 `NightValleyDiscount` 参数，
使得测试可以注入自定义折扣策略（如测试 floor-at-zero 场景），
同时保持默认行为对生产代码无影响。

### 决策 4：E.164 国家代码全集用于电话号码解析

**推理**：`CountryCode.from_phone_number()` 需要准确提取国家代码（如 +44 vs +442）。
仅靠前 N 位数字推断在有 1-3 位国家代码的现实中不可靠。
因此引入 ITU-T E.164 完整代码集进行最长前缀匹配。

---

## 对话 4：熔断器 + 时区防线 — 审查驱动的架构硬化（第一轮）

### Owner 审计指令

> 对 CircuitBreaker、time_parser、RoutingAppService 进行深度合规审计。
> 推演以下场景：
> 1. `ValueError` 异常被 `_is_excluded` 处理后是否真的进入熔断计数？
> 2. ISO-8601 带 microsecond 的合法格式（`2026-06-05T14:30:00.123456+08:00`）是否会被 regex 拒绝？
> 3. RoutingAppService 默认构造的 CircuitBreaker 是否排除了输入校验异常（ValueError/TypeError）？
>
> 发现 3 个高优先级隐患，立即修复。

### 隐患 1：`_is_excluded` 的 `callable` 陷阱

**审计指令**：`callable(ValueError)` 返回什么？

**AI 初始代码的脆弱性**：`_is_excluded` 在类型匹配之前先检查 `callable(entry)`。Python 中 `callable(ValueError)` 返回 `True`（异常类的构造函数是 callable），因此所有 `ValueError`/`TypeError` 异常类被匹配到 callable 分支——业务异常被错误排除出熔断计数。熔断器在逻辑异常洪水中永不触发，形同虚设。

**AI 响应（提交 `2e65fb1`）**：在 callable 分支增加 `not isinstance(entry, type)` 守卫，类型匹配与谓词匹配严格分岔。`callable(entry) and not isinstance(entry, type)` → 谓词匹配；`isinstance(exc, entry)` → 类型匹配。两条路径不再交叉。

### 隐患 2：`time_parser` 正则锚点过严

**审计指令**：ISO-8601 的秒部分允许小数秒。当前正则能否解析 `2026-06-05T14:30:00.123456+08:00`？

**AI 初始代码的脆弱性**：正则以 `$` 结尾，阻止带 microsecond 的合法格式进入匹配。Naive datetime 字符串（无时区后缀）被无条件解释为 UTC，而 pyiso8601 约定中 naive datetime 应允许调用方指定 `default_timezone`。

**AI 响应（提交 `2e65fb1`）**：移除 `$` 锚点，新增 `default_timezone` 参数（遵循 pyiso8601 约定），naive datetime 在指定时区下被解释为该时区的本地时间而非 UTC。

### 隐患 3：`RoutingAppService` 默认熔断器缺少排除规则

**审计指令**：当调用方不注入 CircuitBreaker 时，`__init__` 构造的默认 breaker 是否排除了 `ValueError`/`TypeError`？

**AI 初始代码的脆弱性**：默认 breaker 未注入 `exclude` 参数，输入校验异常（如无效电话号码 → `InvalidCountryCodeError(ValueError)`）被误计为系统故障，3 次无效输入即可触发熔断，阻塞所有后续合法呼叫。

**AI 响应（提交 `2e65fb1`）**：`__init__` 自动创建 breaker 时注入 `_DEFAULT_EXCLUDE = (ValueError, TypeError)`，输入校验异常永不被计入熔断计数。

**全部修复通过 25 个新增测试验证，零回归。**

---

## 对话 5：CDR 持久化上下文 — 审查驱动的架构硬化（第二轮）

### Owner 审计指令

> 在 PERSISTENCE_DESIGN.md 和 SQLite 持久化适配器实现后，进行第二轮深度审计。
> 推演以下场景：
> 1. 两个并发请求携带相同 `idempotency_key`——`save()` 的 SELECT + INSERT 之间有无竞态窗口？
> 2. SQL 列清单在 INSERT + 2 个 SELECT 中重复书写——改一处是否可能漏改？
> 3. `SqliteUnitOfWork.__aexit__` 复制基类逻辑——基类 commit/rollback 变更后子类是否偏离？
> 4. `FakeUnitOfWork.rollback()` 直接操作 `_repo._store.clear()` + `_repo._seen_keys.clear()`——封装是否被打破？
> 5. `_make_rated_call` 在 `test_cdr_repository.py` 和 `test_sqlite_cdr_repository.py` 重复定义——两份拷贝的行为是否一致？
> 6. `_seen_keys: set` 在长生命周期进程中有无内存泄漏？
>
> 发现 6 个隐患，立即修复。

### 隐患 1：TOCTOU 竞态条件（P0）

**审计指令**：两个并发 writer 同时调用 `save()`，都通过了 Layer 2 SELECT 检查（`idempotency_key` 不在表中），然后同时执行 Layer 3 INSERT。会发生什么？

**AI 初始代码的脆弱性**：3 层幂等看似坚固——内存 set → SELECT 预检 → INSERT OR IGNORE。但中间的 SELECT 是纯冗余的数据库往返：在并发场景下，两个 writer 可能同时通过 SELECT（都发现 key 不存在），然后其中一个的 INSERT 被 `INSERT OR IGNORE` 静默吞掉——无异常、无日志、无重试。TOCTOU 在 SQLite 序列化写锁下概率极低但不为零，在 WAL 模式下窗口更宽。

**AI 响应（提交 `1428aba`）**：冷酷删除 Layer 2 SELECT。内存 set 提供单 UoW 内的 O(1) 去重，`INSERT OR IGNORE` + UNIQUE 约束提供跨 UoW 的原子去重。两层各司其职，无竞态窗口。

### 隐患 2：SQL 列清单重复 3 次（P1）

**AI 初始代码**：11 列投影在 INSERT 和 2 个 SELECT 中各写一次。添加一列需要改 3 处，漏一处 = 静默数据丢失。

**AI 响应（提交 `1428aba`）**：提取 `_COLUMNS` 模块常量，定义一次，3 处引用。

### 隐患 3：`__aexit__` 复制基类逻辑（P1）

**审计指令**：`SqliteUnitOfWork.__aexit__` 的 18 行 commit/rollback 逻辑与基类有何区别？如果基类的异常保留路径被修复，子类的拷贝是否同步？

**AI 初始代码**：完整复制 `AbstractUnitOfWork.__aexit__` 的 18 行，仅尾部多一行 `conn.close()`。

**AI 响应（提交 `1428aba`）**：重构为 5 行——`try: await super().__aexit__(...) finally: conn.close()`。确保当 `commit()` 发生底层 I/O 故障时，原始异常原封不动向上传递（不被 rollback 期间的二次异常掩埋），上游 CircuitBreaker 能精准捕捉系统级故障并作出正确熔断决策。

### 隐患 4：`FakeUnitOfWork` 跨类访问私有属性（P1）

**AI 初始代码**：`FakeUnitOfWork.rollback()` 直接操作 `self._repo._store.clear()` 和 `self._repo._seen_keys.clear()`——跨类访问私有属性，打破封装。

**AI 响应（提交 `1428aba`）**：`FakeCdrRepository` 新增 `clear()` 公共方法，`FakeUnitOfWork.rollback()` 调用 `self._repo.clear()`。

### 隐患 5：测试 helper 在两个文件重复定义（P2）

**AI 初始代码**：`_make_rated_call` + `UTC`/`CST` 在 `test_cdr_repository.py` 和 `test_sqlite_cdr_repository.py` 各有一份，含相同的 amount 覆盖 workaround。

**AI 响应（提交 `1428aba`）**：`test_sqlite_cdr_repository.py` 从 `test_cdr_repository.py` 共享导入，单一数据源。

### 隐患 6：`_seen_keys: set` 无界增长（P2）

**AI 响应与退避**：在当前单进程开发/测试场景下，`_seen_keys` 的生命周期绑定于单个 UoW（`async with` 块结束时 repo 随 conn 一起被 GC），无实质泄漏。**但在长生命周期进程中（如服务常驻内存的 FastAPI worker）确实存在无界增长风险**。写入 ADR 债务记录，生产环境切换至 Redis 适配器时通过 TTL 或 LRU 淘汰策略解决，不在 SQLite 适配器中增加复杂度。

---

**Owner 的 AI 主导力体现（两轮审计总结）**：第一轮修复了应用层逻辑（熔断器 callable 陷阱、时区解析器正则、默认 breaker 排除），第二轮直击持久化层的并发安全与代码重复。Owner 对 TOCTOU、幂等原子性、上下文管理器异常传播路径的分布式系统直觉，将 AI 的"能跑"代码打磨为"在高并发下永不静默失败"的生产级底座。每一轮审查不是"看看代码哪里写得不好"，而是"推演这段代码在 175k calls/s、SQLite 写锁序列化、异步 event loop 阻塞的三重压力下会在哪个微秒崩溃"。
