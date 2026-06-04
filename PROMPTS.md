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
因此 `calculate(context, customer_tier)` 而非 `calculate(context)` 隐含从 caller 推断身份。

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
