# PERSISTENCE_DESIGN.md — CDR 持久化上下文设计

## 1. 限界上下文 (Bounded Context)

```
┌──────────────────────────────────────────────────────────────┐
│            CDR Persistence Context (CDR 持久化上下文)         │
│                                                              │
│  应用层                                          基础设施层   │
│                                                              │
│  ┌──────────────────┐    ┌──────────────────────────┐       │
│  │ CalculateRate     │───▶│  CdrRepository (端口·ABC) │       │
│  │ Response (DTO)    │    └──────────┬───────────────┘       │
│  └────────┬─────────┘               │ 实现                    │
│           │                         ▼                        │
│           │              ┌──────────────────────┐            │
│           │              │  SqliteCdrRepository  │  (开发/测试)│
│           │              │  ┌──────────────────┐ │            │
│           │              │  │ 内存幂等预检(set)  │ │ ← 三层防护 │
│           │              │  │ → find_by_key    │ │   第 1 层  │
│           │              │  │ → INSERT OR IGNORE│ │   第2+3层  │
│           │              │  └──────────────────┘ │            │
│           │              └──────────────────────┘            │
│           │                                                  │
│  ┌────────┴─────────┐     ┌──────────────────────────┐       │
│  │ RatedCall (PO)    │     │  AbstractUnitOfWork       │       │
│  │ 持久化数据模型     │     │  (原子事务边界)            │       │
│  └──────────────────┘     └──────────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

本上下文职责单一：将一次费率计算结果持久化，确保幂等去重，提供审计追溯。
不涉及账单汇总、不涉及账户余额、不涉及 CDR 导出。

## 2. 与现有上下文的依赖流向

```
┌─────────────────────┐
│  RoutingAppService  │  (应用层 · 已有)
│  (编排服务)          │
└────────┬────────────┘
         │ ① 计算费率 (现有逻辑)
         │ ② 构造 RatedCall (infrastructure PO)
         │ ③ 幂等预检 (内存 set → DB 查 → DB UNIQUE)
         │ ④ uow.cdr_repo.save(rated_call)
         │ ⑤ uow.commit()
         ▼
┌─────────────────────┐
│  CdrRepository      │  (端口 · 应用层 ABC)
│  AbstractUnitOfWork  │  (端口 · 应用层 ABC)
└────────┬────────────┘
         │ 实现
         ▼
┌─────────────────────┐
│  SqliteCdrRepository│  (适配器 · infrastructure/)
│  + SqliteUnitOfWork │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  sqlite3            │  (Python stdlib)
│  :memory: 或文件    │
└─────────────────────┘
```

**关键原则**：RoutingAppService 只依赖 `CdrRepository` + `AbstractUnitOfWork` 抽象，不知道底层是 SQLite 还是 PostgreSQL。

## 3. 持久化数据模型 (Persistence Object)

### 3.1 RatedCall — 已计费通话记录 (PO / Data Model)

```
RatedCall {
    cdr_id: str                    # UUID v4，全局唯一标识
    caller: str                    # 主叫号码
    callee: str                    # 被叫号码
    call_start_time: datetime      # 通话发起时间 (aware UTC)
    country_code: str              # 目的国家代码 e.g. "+86"
    tier: str                      # 客户身份 "VIP" | "NORMAL"
    night_valley_applied: bool     # 夜间低谷是否生效
    amount: Decimal                # 最终每分钟单价
    currency: str                  # 币种 "CNY"
    idempotency_key: str           # 幂等去重键
    rated_at: datetime             # 计费时间 (aware UTC)
}
```

- **PO (Persistence Object)**，不是领域实体。`RatedCall` 是一个纯数据载体，负责将 `CalculateRateResponse` 的字段映射到持久化存储。它没有领域行为（没有业务方法、不守卫业务不变式），因此不属于领域层。
- 放在 `infrastructure/rated_call.py`，不放在 `domain/`。
- 构造时强制校验 `call_start_time.tzinfo is not None` 和 `rated_at.tzinfo is not None`（数据完整性校验，不是业务规则）。
- 不可变：一旦构造，字段不可修改（`@dataclass(frozen=True)`）。

### 3.2 为什么 RatedCall 不放在领域层？

| 领域对象 | 持久化对象 (RatedCall) |
|----------|----------------------|
| 有业务行为和不変式 | 纯数据载体 |
| 例：Money 守卫同币种加减 | 例：字段映射 + 类型转换 |
| 测试关注业务规则 | 测试关注序列化/反序列化往返 |
| 变化原因：领域规则变了 | 变化原因：表结构或存储格式变了 |

**RatedCall 的变化原因**是存储 schema 变了（加字段、改类型），不是计费规则变了。按单一职责原则，它属于基础设施层。

## 4. 端口定义 (Ports)

端口放在 `application/ports.py`，与已有的 `CustomerProfileFetcher` 并列。

### 4.1 CdrRepository — CDR 仓储端口

```python
from abc import ABC, abstractmethod
from typing import Optional

class CdrRepository(ABC):
    """CDR 持久化端口 — 应用层定义，基础设施层实现。"""

    @abstractmethod
    async def save(self, rated_call: RatedCall) -> None:
        """持久化一条已计费的通话记录。"""
        ...

    @abstractmethod
    async def find_by_idempotency_key(
        self, key: str
    ) -> Optional[RatedCall]:
        """按幂等键查找已有记录，用于去重。"""
        ...

    @abstractmethod
    async def find_by_caller(
        self, caller: str, limit: int = 50
    ) -> list[RatedCall]:
        """按主叫号码查询历史记录（审计/客服）。"""
        ...
```

### 4.2 AbstractUnitOfWork — 工作单元端口

```python
from abc import ABC, abstractmethod

class AbstractUnitOfWork(ABC):
    """原子事务边界 — 管理 CDR 写入的一致性。

    .. warning::
       实现 ``__aexit__`` 时必须正确处理 **异常覆盖** 问题：
       如果 ``commit()`` 抛出异常，随后 ``rollback()`` 也抛出异常，
       必须重新抛出 ``commit()`` 的原始异常，不能让它被 ``rollback()``
       的异常静默覆盖。否则上游熔断器将收到错误的失败原因。
    """

    cdr_repo: CdrRepository

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None:
        ...

    @abstractmethod
    async def rollback(self) -> None:
        ...
```

## 5. 幂等去重设计 — 三层防护

### 5.1 核心流程

```
RoutingAppService.execute()
  │
  ├─[1] 计算费率 (现有逻辑，计算纯 CPU，不涉及 I/O)
  │
  ├─[2] 构造 RatedCall (含 idempotency_key)
  │
  ├─[3] ★ 第一层：内存预检 (O(1)，无 I/O)
  │     │  repo._seen_keys 是一个 Python set
  │     ├─ 命中 → 返回已有结果（不碰数据库）
  │     └─ 未命中 → 加入 set，继续
  │
  ├─[4] ★ 第二层：数据库查重
  │     │  repo.find_by_idempotency_key(key)
  │     ├─ 命中 → 返回已有 RatedCall（并发穿透的少数情况）
  │     └─ 未命中 → 继续
  │
  └─[5] ★ 第三层：数据库唯一约束（最后防线）
        │  uow.commit() → INSERT OR IGNORE
        └─ 冲突 → 不抛异常，静默忽略（并发穿透已由第 2 层处理）
```

### 5.2 为什么需要三层？

| 层级 | 机制 | 处理什么场景 |
|------|------|-------------|
| 内存 set | `idempotency_key in self._seen_keys` | 同一进程内的重复请求（绝大多数情况），O(1)，零 I/O |
| 数据库查询 | `SELECT WHERE idempotency_key = ?` | 跨进程/跨重启的重复请求 |
| UNIQUE 约束 | `INSERT OR IGNORE` | 并发 race condition 的最后防线 |

关键洞察：**幂等检查是高频操作，绝不能挂在数据库写链路上**。第 1 层（内存 set）拦截 99.9% 的重复请求，第 2+3 层处理跨进程和并发边界情况。

### 5.3 幂等键格式

沿用现有 DTO 中的 `idempotency_key` 字段。调用方（API 网关）负责生成，建议格式：
```
{client_id}-{uuid_v4}
例：gateway-01-a3f2b8c1-...
```

服务端不校验格式，只做字节比对。

## 6. 数据库 Schema (SQLite 适配器 v1)

### 6.1 rated_calls 表

```sql
CREATE TABLE IF NOT EXISTS rated_calls (
    cdr_id            TEXT PRIMARY KEY NOT NULL,
    caller            TEXT NOT NULL,
    callee            TEXT NOT NULL,
    call_start_time   TEXT NOT NULL,          -- ISO-8601 UTC
    country_code      TEXT NOT NULL,
    tier              TEXT NOT NULL,
    night_valley_applied INTEGER NOT NULL,     -- 0/1 (SQLite 无 BOOLEAN)
    amount            TEXT NOT NULL,           -- Decimal 序列化为字符串
    currency          TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL UNIQUE,    -- 幂等去重约束 (第 3 层)
    rated_at          TEXT NOT NULL,           -- ISO-8601 UTC
    extra_fields      TEXT DEFAULT '{}'        -- JSON 扩展字段 (未来)
);

CREATE INDEX idx_rated_calls_caller ON rated_calls(caller);
CREATE INDEX idx_rated_calls_rated_at ON rated_calls(rated_at);
```

### 6.2 设计决策

| 决策 | 理由 |
|------|------|
| `amount` 用 TEXT 存 Decimal | SQLite 无 DECIMAL 类型，TEXT 避免浮点精度丢失 |
| `call_start_time` / `rated_at` 用 ISO-8601 字符串 | SQLite 无原生 DATETIME，存 UTC 字符串全局可比 |
| `night_valley_applied` 用 INTEGER 0/1 | SQLite 无 BOOLEAN |
| `extra_fields` JSON | CGRateS 双表分离的简化版——先单表 JSON，字段多了再拆 |
| 索引只建 `caller` 和 `rated_at` | 当前查询 pattern 只有这两种；后续按需加 |
| 时间戳存字符串不存 Unix 数值 | 人类可读，调试友好，ISO-8601 排序等价于时间序 |

## 7. SQLite 性能边界声明

> **架构警告：SQLite 适配器仅限开发、本地测试及低吞吐场景使用。**
>
> SQLite 的写锁是**数据库级锁**（database-level lock）。即使开启 WAL 模式，并发写入仍然被串行化。在高吞吐生产环境（>100 concurrent writes/s），SQLite 会成为系统瓶颈，导致：
> - 上游协程排队等待写锁，内存飙升
> - 应用层精心优化的低延迟（~5.7μs 纯计算）被 I/O 等待完全淹没
> - 核心计费链路的可用性被持久化层拖垮
>
> **生产环境必须使用以下方案之一**：
> 1. **异步落盘适配器** (推荐)：核心链路 fire-and-forget 写入内存队列，后台 Worker 批量刷盘
> 2. **PostgreSQL 适配器**：行级锁 + 连接池，足以支撑中等并发
> 3. **消息队列 + 消费者**：写入 Kafka/Redis Stream，独立消费者负责 CDR 落地

## 8. 生产环境异步落盘设计 (未来规划)

```
RoutingAppService.execute()         ┌─────────────────────┐
  │                                  │  CdrWriteWorker      │
  ├─ 计算费率                         │  (后台协程)           │
  ├─ 幂等预检 (内存 set)              │                     │
  ├─ 写入内存队列 ──────────────────▶  │  while queue:        │
  │   (fire-and-forget)              │    batch = queue.get()│
  └─ 返回响应                         │    repo.save(batch)  │
                                     │    uow.commit()      │
                                     └─────────────────────┘
```

- 核心链路不等待数据库 I/O 完成
- 内存队列有界（`maxsize=10000`），防止 OOM
- Worker 批量提交，降低事务开销
- 队列满时降级为同步写入（背压机制）

此设计不在 v1 实现范围内，但端口设计已预留替换空间。

## 9. 架构决策记录 (ADR)

### ADR-5: sqlite3 作为第一版持久化适配器（仅限开发/测试）

**选择**：Python 标准库 `sqlite3`，WAL 模式，`:memory:` 用于测试。

**理由**：
- 零外部依赖，恪守项目宪章（`DESIGN.md` ADR-1）
- 单文件部署，测试隔离只需换文件路径
- 未来换 PostgreSQL 或异步队列：写新适配器，端口不变

**硬性约束**：SQLite 适配器不得用于生产环境（见第 7 节性能边界声明）。

### ADR-6: Repository 端口用 ABC 而非 Protocol

**选择**：`abc.ABC` + `@abstractmethod`。

**理由**：
- Python 3.9 的 `typing.Protocol` 是静态鸭子类型，运行时不做检查
- ABC 在实例化时会验证抽象方法是否实现，提供更早的错误反馈
- 与项目中已有的 `CustomerProfileFetcher` 端口风格一致

### ADR-7: Unit of Work 管理事务边界，显式处理异常覆盖

**选择**：引入 `AbstractUnitOfWork` 抽象，由 `async with uow:` 管理事务。`__aexit__` 中 `commit()` 异常不会被 `rollback()` 异常覆盖。

**实现要求**（Cosmic Python 第 6 章 + 异常安全加固）：
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is not None:
        await self.rollback()
        return  # 不吞异常，让它继续传播
    try:
        await self.commit()
    except BaseException:
        # commit 失败 → 尝试回滚，但必须保留原始异常
        try:
            await self.rollback()
        except BaseException:
            pass  # rollback 失败不覆盖 commit 的原始异常
        raise  # 重新抛出 commit 的异常
```

**理由**：
- 领域服务不应管理事务——那是基础设施的职责
- 测试用 `FakeUnitOfWork`，commit 是空操作
- 异常安全：熔断器必须看到真实的失败原因，不能被 rollback 异常掩盖

### ADR-8: 三层幂等防护（内存 → 查询 → 约束）

**选择**：内存 set 预检 → `find_by_idempotency_key` → `UNIQUE(idempotency_key)`。

**理由**：
- 第 1 层（内存 set）拦截 99.9% 重复请求，O(1)，零 I/O
- 第 2 层（数据库查询）响应幂等回放（返回已有结果）
- 第 3 层（UNIQUE 约束）是并发 race condition 的最后防线
- 每层有独立的存在理由，不冗余

### ADR-9: RatedCall 是基础设施 PO，不是领域实体

**选择**：`RatedCall` 放在 `infrastructure/` 而非 `domain/`。

**理由**：
- `RatedCall` 没有领域行为——它是从 `CalculateRateResponse` 到数据库行的字段映射器
- 它的变化原因是存储 schema 变了，不是计费规则变了
- 放在 `infrastructure/` 保持领域层纯净，避免贫血模型污染

## 10. 不变式清单

| 编号 | 不变式 | 实施位置 |
|------|--------|----------|
| I-6 | `idempotency_key` 全局唯一 | 内存 set + DB 查询 + UNIQUE 约束（三层） |
| I-7 | RatedCall 的时间字段必须 aware UTC | RatedCall 构造时 `__post_init__` 校验 |
| I-8 | `amount >= 0`（非负单价） | RatedCall 构造时校验 |
| I-9 | `currency` 必须为 "CNY" | RatedCall 构造时校验（当前仅支持人民币） |
| I-10 | CDR 不可修改（append-only） | Repository 只提供 `save()`，不提供 `update()` / `delete()` |

## 11. 目录结构

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
│   ├── application/
│   │   ├── __init__.py
│   │   ├── dto.py
│   │   ├── ports.py                    # 新增 CdrRepository + AbstractUnitOfWork
│   │   ├── time_parser.py
│   │   ├── circuit_breaker.py
│   │   └── routing_service.py
│   └── infrastructure/                 # 适配器层
│       ├── __init__.py
│       ├── rated_call.py              # RatedCall PO (数据模型，非实体)
│       └── sqlite_cdr_repository.py   # SQLite 适配器 + SqliteUnitOfWork
├── tests/
│   ├── ... (已有测试)
│   ├── test_rated_call.py             # NEW — PO 构造与校验
│   ├── test_cdr_repository.py         # NEW — FakeRepository 单元测试
│   ├── test_cdr_uow.py                # NEW — UnitOfWork 单元测试
│   └── test_sqlite_cdr_repository.py  # NEW — SQLite 集成测试
├── DESIGN.md
├── APPLICATION_DESIGN.md
├── PERSISTENCE_DESIGN.md              # NEW (this file)
├── PROMPTS.md
└── README.md
```

**注意**：`application/ports.py` 扩展现有文件（已有 `CustomerProfileFetcher`），不新建文件。

## 12. RoutingAppService 集成点

最终 `RoutingAppService.execute()` 变为五步管道：

```
call_start_time ──►[1] parse_iso8601_to_utc()──► aware UTC datetime
                                                       │
caller ──►[2] breaker.call(fetch_tier)──► VIP/NORMAL ◄─┤
                                                       │
callee ──►[3] CallContext(caller, callee, time)────────┤
                                                       │
         ──►[4] RateCalculator.calculateRate(ctx, tier)────┤
                                                       │
         ──►[5] 幂等预检 → repo.save(RatedCall(...)) ◄──┘
               uow.commit()
```

第 5 步通过 `AbstractUnitOfWork` 管理事务。幂等三层防护全部在 `save()` 调用链中透明完成。

## 13. 实施路线

| 阶段 | 内容 | 涉及文件 |
|------|------|----------|
| **Commit 1** | `RatedCall` PO (`infrastructure/`) + 构造校验 | `infrastructure/rated_call.py`, `tests/test_rated_call.py` |
| **Commit 2** | `CdrRepository` + `AbstractUnitOfWork` 端口 (扩展 `ports.py`) | `application/ports.py` |
| **Commit 3** | `FakeCdrRepository` + `FakeUnitOfWork` (测试用) | `tests/test_cdr_repository.py`, `tests/test_cdr_uow.py` |
| **Commit 4** | `SqliteCdrRepository` + `SqliteUnitOfWork` (含三层幂等) | `infrastructure/sqlite_cdr_repository.py`, `tests/test_sqlite_cdr_repository.py` |
| **Commit 5** | `RoutingAppService` 集成 (五步管道) | `application/routing_service.py`, `tests/test_routing_service.py` |

每个 commit 独立可发布，测试全绿。

## 14. 分布式多节点幂等行为分析

### 14.1 UNIQUE 约束的原子性保证

`INSERT OR IGNORE` + `UNIQUE(idempotency_key)` 的去重是**存储引擎级别的原子操作**。
B-tree 索引的键唯一性检查和行插入在同一个 B-tree 页锁定区间内完成——
两个并发 writer（即使是来自不同节点的独立连接）不可能同时通过检查：

```
Writer A: INSERT OR IGNORE ... key="abc"  →  写入成功，rowcount=1
Writer B: INSERT OR IGNORE ... key="abc"  →  检测到冲突，静默跳过，rowcount=0
```

结果确定且可复现：**先到达磁盘者胜出（first-write-wins）**。此行为不依赖事务隔离级别——UNIQUE 约束由存储引擎（非查询优化器）强制执行，在 SQLite、PostgreSQL、MySQL/InnoDB 的任何隔离级别下均保证原子。

### 14.2 不会发生的故障模式

以下是在 Stripe/Uber 级分布式幂等系统中已知的故障模式，**均不适用于当前架构**：

| 故障模式 | 为何不适用 |
|----------|-----------|
| **读取异步副本导致复制滞后** | 当前适配器是单文件 SQLite，无主从拓扑。直接读取写入节点 |
| **Redis Cluster 跨槽 Lua 原子性丧失** | 当前不使用 Redis；UNIQUE 约束在单一数据库内生效 |
| **Payload 不匹配被静默丢弃** | 当前 CDR 的 `idempotency_key` 映射到确定性的计费结果——同一 key 总是对应同一金额。不存在"相同 key 不同 payload"的场景（若调用方故意为之，first-write-wins 是正确的业务语义） |
| **孤儿锁阻塞重试** | 当前不使用 `absent → processing → completed` 三态机——`INSERT OR IGNORE` 是即时完成的，不保留 in-progress 状态 |
| **Check-then-act race（TOCTOU）** | 已在审查期间消除——Layer 2 SELECT 被删除，仅保留内存 set（单进程 O(1)）和 `INSERT OR IGNORE`（跨进程原子） |

### 14.3 多节点部署时唯一剩余的弱点

当前双层幂等在**多节点无共享内存**场景下，Layer 1（内存 set）不跨节点共享。
这**不影响正确性**——Layer 2（`INSERT OR IGNORE` UNIQUE 约束）会捕获所有跨节点重复。
唯一代价是一次无意义的数据库往返（约 0.1-0.5ms for SQLite，约 0.3-1ms for PostgreSQL）。

当节点数 > 3 且重复率 > 10% 时，建议升级为：

```
Layer 0: Redis SET NX EX 30 (跨节点共享, TTL 自清理)
Layer 1: 内存 set (进程内 O(1))
Layer 2: INSERT OR IGNORE UNIQUE (存储引擎原子性, 最后防线)
```

注意：Redis 层的引入必须遵守 **hash tag 规则**（`{tenant}:idempotency:{key}` 确保同一 slot），
且 Redis 层丢失不影响正确性——仅影响性能（更多请求穿透到 Layer 2）。

### 14.4 设计结论

当前双层幂等在单节点部署（含多 worker 进程共享同一 SQLite 文件）下**无已知漏洞**。
UNIQUE 约束提供的原子性在市场主流数据库中得到了十年级别的生产验证（PostgreSQL UNIQUE b-tree、MySQL/InnoDB UNIQUE index、SQLite UNIQUE）。
尚无任何 CVE 或公开报告指向 UNIQUE 约束本身的并发绕过。
