# 第四步：时间线与持久化

## 环节定位

L-Agent 实施计划的第四步。将前三步运行在内存中的 session、message、run 状态持久化到存储层。定义 Session / Branch / AgentRun / Message / Checkpoint 完整数据模型，先提供基于 SQLite 存储的实现，并将生命周期中的 commit/checkpoint steps 接入真实持久化。

## 注意事项

- message.commit_user 和 checkpoint.create_user_snapshot 共同形成 rewind 边界，暂不考虑事务一致性问题
- 对于包含 tool_calls 的 assistant message ，也需要 commit 到 message timeline
- runtime checkpoint 由 AgentRunner 在 action 边界自动记录
- user_message_committed 是第一版唯一用户可见 checkpoint
- 存储层先做接口抽象（TimelineStore），再做 SQLite 实现，不绑死具体存储
- Branch 的 base_message_cursor 用于结构共享，不复制旧消息
- 当前设计阶段不展开事务细节，先保证语义正确；复杂事务与恢复修复策略在第八步独立设计

## 详细内容

### 4.1 数据模型

**Session**：长期会话容器，表示用户可感知的一次连续工作上下文

- session_id：唯一标识
- title：会话标题
- active_branch_id：当前活跃 branch
- created_at / updated_at
- metadata / stats

**Branch**：Session 内的一条上下文时间线

- branch_id：唯一标识
- session_id：所属 session
- parent_branch_id：父 branch（rewind fork 时设置）
- fork_checkpoint_id：从哪个 checkpoint fork 出来
- base_message_cursor：结构共享的消息游标
- resume_head：最新完整运行结果的 checkpoint 引用

**AgentRun**：Agent 响应一次输入的完整运行事务

- run_id：唯一标识
- session_id / branch_id
- status：running / completed / failed / interrupted
- created_at / completed_at

**ReActIteration**：AgentRun 内的一轮模型决策与可选工具行动

- iteration_id：唯一标识
- run_id：所属 run
- index：轮次序号

**Message**：conversation timeline 的事实记录

- message_id：唯一标识
- session_id / branch_id / run_id
- sequence：在 branch 内的序号（递增）
- role：system / user / assistant / tool
- content：消息内容
- tool_call_id：tool result 对应的 call id（role=tool 时）
- tool_calls：assistant 请求的工具调用（role=assistant 时，可选）
- created_at

**Checkpoint**：Branch 时间线上的恢复边界

- checkpoint_id：唯一标识
- session_id / branch_id / run_id
- kind：user_snapshot / runtime
- name：checkpoint 名称（如 user_message_committed / model_call_started）
- message_cursor：恢复时消息读到哪里
- created_at

### 4.2 存储层

**TimelineStore 接口**：

- Session CRUD
- Branch CRUD
- AgentRun CRUD
- Message：append / get_by_branch(cursor_range) / get_latest_sequence
- Checkpoint：create / get_by_branch / get_latest_stable

**SQLite 实现**：

- schema.py：建表语句
- sqlite.py：TimelineStore 的 SQLite 实现
- 数据库文件存放在 workspace/state.db

### 4.3 生命周期 steps 接入持久化

before_agent 新增/改造 steps：

- `run.create`：向 TimelineStore 写入 AgentRun 记录（status=running）
- `message.commit_user`：将用户输入写为 role=user message 到 branch timeline
- `checkpoint.create_user_snapshot`：创建 kind=user_snapshot / name=user_message_committed 的 checkpoint

after_model 改造：

- `message.commit_assistant`：将 assistant message 持久化（包括含 tool_calls 的中间 message）

after_tool 改造：

- `message.commit_tool_results`：将每个 tool result 持久化为 role=tool message
- `checkpoint.record_tool_results_committed`：创建 runtime checkpoint

after_agent 新增/改造：

- `run.mark_terminal_state`：更新 AgentRun status 为 completed / failed / interrupted
- `checkpoint.record_run_terminal_state`：创建 run_completed / run_failed / run_interrupted runtime checkpoint

### 4.4 AgentRunner checkpoint 接口落地

AgentRunner 在 action 边界自动调用 TimelineStore 记录 runtime checkpoint：

- model_call_started（action 执行前）
- model_call_completed / model_call_failed（action 执行后）
- tool_call_started（action 执行前）
- tool_call_completed / tool_call_failed（action 执行后）

### 4.5 关键规则

- resume：使用 active branch 最新完整 run 状态
- rewind：使用 user_message_committed checkpoint 创建新 branch
- user_message_committed：第一版唯一用户可见 checkpoint
- runtime checkpoints：用于内部恢复、诊断和副作用安全判断

## Todo List

| # | 任务 | 状态 |
|---|------|------|
| 4.1 | 定义 `Session` 数据模型 | done |
| 4.2 | 定义 `Branch` 数据模型 | done |
| 4.3 | 定义 `AgentRun` 数据模型 | done |
| 4.4 | 定义 `ReActIteration` 数据模型 | done |
| 4.5 | 定义 `Message` 数据模型 | done |
| 4.6 | 定义 `Checkpoint` 数据模型（kind: user_snapshot / runtime） | done |
| 4.7 | 设计 `TimelineStore` 接口（Session/Branch/Run/Message/Checkpoint CRUD） | done |
| 4.8 | 设计 SQLite schema（建表语句） | done |
| 4.9 | 实现 SQLite 存储层 | done |
| 4.10 | 实现 before_agent step `run.create`（写 AgentRun 记录） | done |
| 4.11 | 实现 before_agent step `message.commit_user`（持久化 user message） | done |
| 4.12 | 实现 before_agent step `checkpoint.create_user_snapshot` | done |
| 4.13 | 改造 after_model step `message.commit_assistant`（接入持久化） | done |
| 4.14 | 改造 after_tool step `message.commit_tool_results`（接入持久化） | done |
| 4.15 | 实现 after_tool step `checkpoint.record_tool_results_committed` | done |
| 4.16 | 实现 after_agent step `run.mark_terminal_state` | done |
| 4.17 | 实现 after_agent step `checkpoint.record_run_terminal_state` | done |
| 4.18 | AgentRunner checkpoint 接口落地（model_call/tool_call started/completed/failed） | done |
| 4.19 | 编写测试：完整 AgentRun 后验证 SQLite 中 session 数据 | done |
| 4.20 | 编写测试：验证 message sequence 正确递增 | done |
| 4.21 | 编写测试：验证 checkpoint message_cursor 正确指向 | done |
| 4.22 | 编写测试：验证 runtime checkpoint 正确记录 | done |

## 交付与验收标准

- [x] 一次完整 AgentRun 后，SQLite 中有完整的 session / branch / run / messages / checkpoints 记录
- [x] 消息 sequence 正确递增，无间隔
- [x] checkpoint 的 message_cursor 正确指向对应消息
- [x] user_message_committed checkpoint 正确创建（kind=user_snapshot）
- [x] assistant_message_committed checkpoint 正确创建（kind=runtime）
- [x] tool_results_committed checkpoint 正确创建（kind=runtime）
- [x] runtime checkpoint（model_call_started/completed, tool_call_started/completed）正确记录
- [x] run 状态正确标记为 completed / failed / interrupted
- [x] TimelineStore 接口与 SQLite 实现解耦，可替换
- [x] 所有测试通过
