# 第六步：CLI 与用户交互

## 环节定位

L-Agent 实施计划的第六步。将前五步构建的 Agent 内核封装为可日常使用的 CLI 工具。实现用户输入主循环、会话管理命令、工具审批交互和运行状态展示。本步同时将 AgentRunner 改造为 async generator 事件流模型，以支持流式输出体验。

## 注意事项

- CLI 是 Agent 的一个入口，不是 Agent 本身；CLI 调用 Agent，不应反过来让 Agent 依赖 CLI
- 工具审批交互需要阻塞 AgentRun，等待用户确认后再继续
- auto-approve 规则应可配置，避免每次都手动确认安全工具
- 输出展示要区分 assistant 最终回复和中间工具调用过程
- session 管理命令（list/resume/rewind）是 CLI 层功能，不是 Agent 生命周期的一部分
- CLI 不应该把展示逻辑耦合进 Agent 内核
- AgentRunner 改为 async generator，所有现有测试同步改造为 async

## 技术选型

| 用途 | 选择 | 说明 |
|------|------|------|
| 终端输入 | prompt_toolkit | 按键绑定、多行编辑、async prompt |
| 终端渲染 | Rich | Markdown 渲染、语法高亮、spinner、panel |
| CLI 入口 | typer | type hint 驱动的参数解析，底层 click |
| 配置格式 | YAML | 可读性好，支持注释 |
| 异步框架 | asyncio | 标准库，与 LLM SDK / prompt_toolkit 兼容 |

## 详细内容

### 6.1 事件流模型

AgentRunner.run() 改造为 async generator，yield 事件流供 CLI 消费：

```python
class AgentRunner:
    async def run(self, ctx: RunContext) -> AsyncGenerator[AgentEvent, None]:
        yield RunStart()
        try:
            async for event in self._react_loop(ctx):
                yield event
            yield RunDone(status=ctx.status, result=ctx.final_result)
        except Exception as exc:
            yield RunError(error=exc)
```

### 6.2 事件类型定义

```python
# agent/events.py

@dataclass(frozen=True)
class AgentEvent:
    pass

# --- Model ---
class ModelStart(AgentEvent): pass

class Token(AgentEvent):
    text: str

class ModelDone(AgentEvent):
    response: ModelResponse

# --- Tool ---
class ToolStart(AgentEvent):
    tool_name: str
    arguments: dict

class ToolDone(AgentEvent):
    tool_name: str
    result: Any

# --- Approval ---
class ApprovalRequest(AgentEvent):
    tool_name: str
    arguments: dict
    risk_level: str
    future: asyncio.Future[bool]

# --- Run lifecycle ---
class RunStart(AgentEvent): pass

class RunDone(AgentEvent):
    status: str
    result: Any

class RunError(AgentEvent):
    error: Exception
```

流式只用于模型回复的 token 输出。工具执行非流式（yield ToolStart → 执行完 → yield ToolDone）。

### 6.3 React Loop（async generator）

```python
async def _react_loop(self, ctx: RunContext) -> AsyncGenerator[AgentEvent, None]:
    while True:
        if ctx.interrupted or ctx.budget.exhausted:
            break

        yield ModelStart()
        async for token in self._stream_model_call(ctx):
            yield Token(text=token)
        yield ModelDone(response=ctx.current_model_response)

        if not ctx.has_tool_calls:
            break

        for tool_call in ctx.pending_tool_calls:
            if needs_approval(tool_call):
                future = asyncio.Future()
                yield ApprovalRequest(
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    risk_level=tool_call.risk_level,
                    future=future,
                )
                approved = await future
                if not approved:
                    ctx.record_denied(tool_call)
                    continue

            yield ToolStart(tool_name=tool_call.name, arguments=tool_call.arguments)
            result = await self._execute_tool(tool_call)
            yield ToolDone(tool_name=tool_call.name, result=result)

        ctx.has_tool_calls = False
```

### 6.4 主循环

```
启动:
  → 创建新 session / 恢复已有 session（根据参数或默认行为）
  → 进入循环:
      → 读取用户输入（prompt_toolkit async prompt）
      → 构造 Agent input
      → 启动 AgentRun（async for event in runner.run(ctx)）
      → 实时渲染事件流
      → 等待下一轮输入
  → 退出时保存 session 状态
```

CLI 消费事件流：

```python
async def handle_run(self, ctx: RunContext):
    async for event in self.runner.run(ctx):
        match event:
            case Token(text=t):
                self.render.stream_text(t)
            case ModelDone():
                self.render.finish_stream()
            case ToolStart(tool_name=name):
                self.render.show_tool_spinner(name)
            case ToolDone(tool_name=name, result=r):
                self.render.finish_tool(name, r)
            case ApprovalRequest() as req:
                approved = await self.approval.prompt(req)
                req.future.set_result(approved)
            case RunError(error=e):
                self.render.show_error(e)
```

支持的输入模式：

- 普通文本输入：作为 user message 触发 AgentRun
- 命令输入（/ 前缀）：会话管理等元命令
- ESC 键：中断当前 run，回到输入等待
- Ctrl+C：退出会话（保存 session）

### 6.5 中断处理

- **ESC 键**：通过 prompt_toolkit key binding 捕获，设置 `ctx.interrupted = True`，generator 在下一个 yield 点自然退出，CLI 回到输入等待
- **Ctrl+C**：raise KeyboardInterrupt，CLI 顶层 catch，保存 session，优雅退出

### 6.6 会话管理命令

- `/new`：创建新 session
- `/list`：列出历史 sessions（id / title / updated_at），方向键选择 + 回车确认
- `/resume [session_id]`：恢复指定 session（无参数时展示选择列表）
- `/rewind [n]`：展示 checkpoints 选择列表，方向键选择回退点 + 回车确认
- `/status`：展示当前 session 信息（branch / run count / token usage）

### 6.7 选择式交互

需要用户选择的场景统一使用方向键 + 回车模式：

```python
async def select_prompt(options: list[str], highlight_index: int = 0) -> int:
    """方向键移动高亮，回车确认，ESC 取消（返回 -1）"""
    ...
```

应用场景：

- 工具审批：Yes / No / Always allow
- `/rewind`：选择 checkpoint
- `/resume`：选择 session
- `/list`：选择并恢复 session

渲染效果：

```
  Tool: terminal
  Args: rm -rf /tmp/test
  Risk: high

  ❯ Yes
    No
    Always allow
```

### 6.8 工具审批与 Auto-approve

当 approval guard 判断某工具需要用户确认时，展示选择式交互。

用户选择：

- Yes：本次允许执行，future.set_result(True)
- No：拒绝，future.set_result(False)，生成 denied tool result
- Always allow：将该工具加入 auto-approve 列表，future.set_result(True)

Auto-approve 配置（YAML）：

```yaml
approval:
  auto_approve:
    - think
    - read_file
    - list_directory
  always_confirm:
    - terminal
    - write_file
```

### 6.9 输出展示

区分不同内容的展示方式（使用 Rich）：

- **模型回复流式输出**：逐 token 渲染，支持 Markdown（代码高亮、列表、表格）
- **工具调用过程**：spinner + 工具名，完成后展示结果摘要（可折叠 panel）
- **运行状态**：iteration 数、token 消耗、耗时
- **错误信息**：AgentRun failed / interrupted 时的错误说明

### 6.10 Agent 与 CLI 的边界

Agent 内核通过 async generator yield 事件通知 CLI 层：

- 模型 token 流（CLI 负责实时渲染）
- 工具审批请求（CLI 负责展示选择 + 回填 future）
- 工具执行状态（CLI 负责 spinner + 结果展示）
- 最终结果（CLI 负责展示）

Agent 内核不直接 print 或 input，保持可测试性。审批通过 `asyncio.Future` 实现双向通信。

### 6.11 文件结构

```
agent/
  events.py              ← 事件类型定义
  core/
    runner.py            ← 重写为 async generator
    context.py
    lifecycle.py
  cli/
    app.py               ← CLI 主循环（typer + asyncio）
    render.py            ← Rich 渲染层
    approval.py          ← 选择式审批交互
    commands.py          ← / 命令分发
    select.py            ← 通用选择式交互组件
```

## Todo List

| # | 任务 | 状态 |
|---|------|------|
| 6.1 | 定义事件类型体系（agent/events.py） | done |
| 6.2 | 将 AgentRunner 改造为 async generator | done |
| 6.3 | 将现有测试全部改为 async | done |
| 6.4 | 实现 CLI 主循环（typer 入口 + asyncio event loop） | done |
| 6.5 | 实现文本输入（prompt_toolkit async prompt） | done |
| 6.6 | 实现选择式交互组件（方向键 + 回车） | done |
| 6.7 | 实现模型回复流式渲染（Rich Markdown） | done |
| 6.8 | 实现工具执行状态展示（spinner + 结果 panel） | done |
| 6.9 | 实现工具审批交互（选择式 + Future 回填） | done |
| 6.10 | 实现 auto-approve 配置加载（YAML） | done |
| 6.11 | 实现 ESC 中断当前 run | done |
| 6.12 | 实现 Ctrl+C 退出会话（保存 session） | done |
| 6.13 | 实现 `/new` 命令 | done |
| 6.14 | 实现 `/list` 命令（选择式） | done |
| 6.15 | 实现 `/resume` 命令（选择式） | done |
| 6.16 | 实现 `/rewind` 命令（选择式） | done |
| 6.17 | 实现 `/status` 命令 | done |
| 6.18 | 实现运行状态展示（iteration / token / 耗时） | done |
| 6.19 | 实现错误/中断展示 | done |
| 6.20 | 编写端到端测试：完整对话流程 | done |
| 6.21 | 编写测试：事件流产出正确事件序列 | done |
| 6.22 | 编写测试：会话管理命令 | done |
| 6.23 | 编写测试：工具审批流程（含 Future 回填） | done |

## 交付与验收标准

- [ ] AgentRunner 为 async generator，yield 事件流
- [ ] 模型回复逐 token 流式展示
- [ ] 工具执行有 spinner + 结果展示
- [ ] 工具审批使用方向键选择式交互 + Future 双向通信
- [ ] auto-approve 配置生效（YAML）
- [ ] `/list` / `/resume` / `/rewind` / `/new` / `/status` 命令可用，需选择的用方向键交互
- [ ] ESC 中断当前 run，Ctrl+C 退出会话
- [ ] 异常退出后重新启动，能 resume 上次 session
- [ ] Agent 内核不直接依赖 CLI（通过事件流解耦）
- [ ] 所有测试为 async，全部通过
