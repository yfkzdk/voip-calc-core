# PERSISTENCE_DESIGN.md — CDR 持久化上下文设计

## 1. 限界上下文 (Bounded Context)

```
┌──────────────────────────────────────────────────────────────┐
│               CDR Persistence Context (CDR 持久化上下文)       │
│                                                              │
│  ┌──────────────────┐    ┌──────────────────────────┐       │
│  │ CalculateRate     │───▶│  CdrRepository            │       │
│  │ Response (DTO)    │    │  (端口 · ABC)             │       │
│  └──────────────────┘    └──────────┬───────────────┘       │
│                                     │                        │
│                          ┌──────────┼──────────┐             │
│                          ▼          ▼          ▼             │
│                   SqliteCdrRepo  FakeRepo   PostgresRepo     │
│                   (适配器·v1)   (测试)     (未来)            │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  UnitOfWork                                       │       │
│  │  (原子事务边界 · commit / rollback)                │       │
│  └──────────────────────────────────────────────────┘       │
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
         │ 调用 CdrRepository.save(rated_call)
         ▼
┌─────────────────────┐
│  CdrRepository      │  (端口 · 新增)
│  (ABC)              │
└────────┬────────────┘
         │ 实现
         ▼
┌─────────────────────┐
│  SqliteCdrRepository│  (适配器 · 新增)
│  + SqliteUnitOfWork │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  sqlite3            │  (Python stdlib)
│  rated_calls.db     │
└─────────────────────┘
```

**关键原则**：RoutingAppService 只依赖 `CdrRepository` 抽象，不知道底层是 SQLite 还是 PostgreSQL。

## 3. 领域模型 (Domain Model)

### 3.1 RatedCall — 已计费通话记录 (实体)

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

- **实体**（非值对象），因为 `cdr_id` 是唯一标识，且未来可能有生命周期（如重新计费）。
- 构造时强制校验 `call_start_time.tzinfo is not None` 和 `rated_at.tzinfo is not None`。
- 不可变：一旦构造，字段不可修改（`@dataclass(frozen=True)`）。

### 3.2 为什么 RatedCall 是实体而非值对象？

| 值对象 | 实体 |
|--------|------|
| 无唯一标识，靠值判等 | 有唯一标识 (`cdr_id`) |
| 可被整体替换 | 有自己的生命周期 |
| 例：Money, CountryCode | 例：RatedCall, Order |

RatedCall 由 `cdr_id` 标识，未来可能被重新计费（产生新版本但指向同一通话），因此是实体。

## 4. 端口定义 (Ports)

### 4.1 CdrRepository — CDR 仓储端口

```python
from abc import ABC, abstractmethod
from typing import Optional

class CdrRepository(ABC):
    """CDR 持久化端口 — 领域层定义，适配器实现。"""

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

### 4.2 UnitOfWork — 工作单元端口

```python
from abc import ABC, abstractmethod

class AbstractUnitOfWork(ABC):
    """原子事务边界 — 管理 CDR 写入的一致性。"""

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

## 5. 幂等去重设计

### 5.1 核心流程

```
RoutingAppService.execute()
  │
  ├─[1] 计算费率 (现有逻辑)
  │
  ├─[2] 构造 RatedCall (含 idempotency_key)
  │
  ├─[3] repo.find_by_idempotency_key(key)
  │     ├─ 命中 → 直接返回已有 RatedCall（不重复写入）
  │     └─ 未命中 → 继续
  │
  └─[4] uow.commit() → repo.save(rated_call)
        └─ INSERT OR IGNORE（数据库层兜底）
```

两层防护：
- **应用层**：`find_by_idempotency_key` 先查，避免无效写入
- **数据库层**：`UNIQUE(idempotency_key)` 约束，防止并发穿透

### 5.2 为什么不用 INSERT ... ON CONFLICT DO NOTHING 直接写？

SQLite 支持 `INSERT OR IGNORE`，语义等价。但应用层的先查后写有两个优势：
1. 可以返回"已存在的相同请求"给调用方（幂等响应回放）
2. 减少无效的写入操作，降低 WAL 压力

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
    idempotency_key   TEXT NOT NULL UNIQUE,    -- 幂等去重约束
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

## 7. 架构决策记录 (ADR)

### ADR-5: sqlite3 作为第一版持久化适配器

**选择**：Python 标准库 `sqlite3`，WAL 模式，单文件存储。

**理由**：
- 零外部依赖，恪守项目宪章（`DESIGN.md` ADR-1）
- WAL 模式下读写不互斥，足以支撑中等并发 CDR 写入
- 单文件部署，测试隔离只需换文件路径
- 未来换 PostgreSQL：写一个新的 `PostgresCdrRepository`，领域代码一行不改

**替代方案**：
- PostgreSQL：功能最强，但引入 `asyncpg` 外部依赖，违反当前零依赖原则
- Redis：适合缓存但不适合作为 CDR 的持久化数据源
- 纯文件 (CSV/JSONL)：实现简单但查询和去重困难

### ADR-6: Repository 端口用 ABC 而非 Protocol

**选择**：`abc.ABC` + `@abstractmethod`。

**理由**：
- Python 3.9 的 `typing.Protocol` 是静态鸭子类型，运行时不做检查
- ABC 在实例化时会验证抽象方法是否实现，提供更早的错误反馈
- 与项目中已有的 `CustomerProfileFetcher` 端口风格一致

### ADR-7: Unit of Work 管理事务边界

**选择**：引入 `AbstractUnitOfWork` 抽象，由领域服务通过 `async with uow:` 使用。

**理由**（Cosmic Python 第 6 章）：
- 领域服务不应管理事务——那是基础设施的职责
- UnitOfWork 封装了 commit/rollback 语义，领域代码只需要 `uow.commit()`
- 测试用 `FakeUnitOfWork`，commit 是空操作，数据存内存
- `__aexit__` 自动 rollback 异常，符合"safe by default"原则

### ADR-8: 先查后写 + 数据库约束双层幂等防护

**选择**：应用层 `find_by_idempotency_key` + 数据库 `UNIQUE(idempotency_key)`。

**理由**：
- 应用层查找可以返回幂等响应（复用已有结果）
- 数据库唯一约束是最后防线，防止并发 race condition
- 不是过度设计——`idempotency_key` 从 APPLICATION_DESIGN.md 第一天就在 DTO 里了

## 8. 不变式清单

| 编号 | 不变式 | 实施位置 |
|------|--------|----------|
| I-6 | `idempotency_key` 全局唯一 | `rated_calls` 表 UNIQUE 约束 + `SqliteCdrRepository.save()` |
| I-7 | RatedCall 的时间字段必须 aware UTC | RatedCall 构造时 `__post_init__` 校验 |
| I-8 | `amount >= 0`（非负单价） | RatedCall 构造时校验 |
| I-9 | `currency` 必须为 "CNY" | RatedCall 构造时校验（当前仅支持人民币） |
| I-10 | CDR 不可修改（append-only） | Repository 只提供 `save()`，不提供 `update()` / `delete()` |

## 9. 目录结构

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
│   │   ├── ports.py                    # 新增 CdrRepository + UnitOfWork 端口
│   │   ├── time_parser.py
│   │   ├── circuit_breaker.py
│   │   └── routing_service.py
│   └── infrastructure/                 # NEW — 适配器层
│       ├── __init__.py
│       ├── rated_call.py              # RatedCall 实体
│       └── sqlite_cdr_repository.py   # SQLite 适配器 + SqliteUnitOfWork
├── tests/
│   ├── test_money.py
│   ├── test_country_code.py
│   ├── test_customer_tier.py
│   ├── test_night_valley.py
│   ├── test_rate_calculator.py
│   ├── test_time_parser.py
│   ├── test_circuit_breaker.py
│   ├── test_application_dto.py
│   ├── test_routing_service.py
│   ├── test_rated_call.py             # NEW
│   ├── test_sqlite_cdr_repository.py  # NEW (集成测试，需要真实 sqlite3)
│   └── test_cdr_uow.py                # NEW
├── DESIGN.md
├── APPLICATION_DESIGN.md
├── PERSISTENCE_DESIGN.md              # NEW (this file)
├── PROMPTS.md
└── README.md
```

## 10. RoutingAppService 集成点

最终 `RoutingAppService.execute()` 变为五步管道：

```
call_start_time ──►[1] parse_iso8601_to_utc()──► aware UTC datetime
                                                       │
caller ──►[2] breaker.call(fetch_tier)──► VIP/NORMAL ◄─┤
                                                       │
callee ──►[3] CallContext(caller, callee, time)────────┤
                                                       │
         ──►[4] RateCalculator.calculate(ctx, tier)────┤
                                                       │
         ──►[5] repo.save(RatedCall(...)) ◄────────────┘ (幂等去重)
```

第 5 步通过 UnitOfWork 管理事务：`RateCalculator` 计算完成后 → 构造 `RatedCall` → `uow.cdr_repo.save()` → `uow.commit()`。

## 11. FakeRepository（测试用）

```python
class FakeCdrRepository(CdrRepository):
    """In-memory CDR repository for tests — no database needed."""
    
    def __init__(self):
        self._store: dict[str, RatedCall] = {}
    
    async def save(self, rated_call: RatedCall) -> None:
        if rated_call.idempotency_key in self._store:
            raise DuplicateIdempotencyKeyError(rated_call.idempotency_key)
        self._store[rated_call.idempotency_key] = rated_call
    
    async def find_by_idempotency_key(self, key: str) -> Optional[RatedCall]:
        return self._store.get(key)
    
    async def find_by_caller(self, caller: str, limit: int = 50) -> list[RatedCall]:
        return [rc for rc in self._store.values() if rc.caller == caller][:limit]
```

所有单元测试使用 `FakeCdrRepository` + `FakeUnitOfWork`。唯一的集成测试（`test_sqlite_cdr_repository.py`）使用真实 `sqlite3` 内存数据库（`:memory:`）。

## 12. 实施路线

| 阶段 | 内容 | 预计新增测试 |
|------|------|-------------|
| **Commit 1** | `RatedCall` 实体 + 构造校验 | ~8 测试 |
| **Commit 2** | `CdrRepository` 端口 (ABC) + `FakeCdrRepository` | ~6 测试 |
| **Commit 3** | `AbstractUnitOfWork` 端口 + `FakeUnitOfWork` | ~5 测试 |
| **Commit 4** | `SqliteCdrRepository` 适配器 (WAL 模式, `INSERT OR IGNORE`) | ~8 测试 |
| **Commit 5** | `RoutingAppService` 集成 CdrRepository + UnitOfWork | ~6 测试 (扩展已有) |
| **Commit 6** | `PERSISTENCE_DESIGN.md` 提交 | — |

每个 commit 独立可发布，测试全绿。
