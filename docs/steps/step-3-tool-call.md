# 第三步：工具调用通路

## 环节定位

L-Agent 实施计划的第三步。在模型调用通路基础上，接通工具调用的完整通路：模型请求工具 → 准备执行计划 → 串行执行 → 结果回到上下文 → 继续推理。实现 ReAct 多轮循环的完整闭环。

## 注意事项

- 工具执行保持全串行，第一版不做 parallel_safe
- before_tool 做计划级解析与校验，ToolDispatcher 做最终防御性校验（两层校验）
- approval.guard 拒绝时不终止 AgentRun，而是生成 denied tool result 让模型继续
- before_agent 的 tools.snapshot_available_tools 在本步实现真实逻辑
- 先只实现 think 工具验证通路，其余工具在第七步补全
- tool result 作为 role=tool message 加入 message list，保留 tool_call_id 对应关系
- 即使 assistant message 包含 tool_calls，也必须进入 message timeline（在 after_model 已实现 commit）

## 详细内容

### 3.1 工具基础设施

数据结构：

- `ToolSpec`：name / description / parameters_schema / handler
  - name：工具唯一标识
  - description：工具用途说明（模型可见）
  - parameters_schema：JSON Schema 格式的参数定义
  - handler：实际执行函数
- `ToolCall`：call_id / tool_name / arguments
  - call_id：模型返回的调用标识，用于 tool result 对应
  - tool_name：请求调用的工具名
  - arguments：已解析的参数 dict
- `ToolResult`：call_id / status(success/error/denied) / content
  - status：执行结果状态
  - content：结果内容（字符串）
- `ToolPlan`：calls 列表 / execution_mode=serial
  - 描述本轮所有工具调用的执行计划

组件：

- `ToolRegistry`：
  - register(tool_spec)：注册工具
  - get(name)：获取工具
  - list_schemas()：列出所有工具的 schema（给模型的 tools 参数）
- `ToolDispatcher`：
  - 按 ToolPlan 串行执行
  - 执行前做最终防御性校验（工具存在、参数可解析）
  - 捕获异常，包装为 error 类型 ToolResult
  - 不抛异常到 AgentRunner

### 3.2 after_model 补充

新增 step：

- `tool.detect_requested`：检查 model_response 是否包含 tool_calls，如果有则设置 ctx.has_tool_calls = True

与已有 step 的顺序关系：

```
after_model:
  - model.capture_response
  - message.commit_assistant
  - usage.update
  - result.detect_final_answer    # 无 tool_calls 时设置 final_result
  - tool.detect_requested         # 有 tool_calls 时设置 has_tool_calls
```

### 3.3 before_tool steps

before_tool 的完整职责定义：

> 把模型请求的 tool_calls 转换成可执行、可审计、可安全处理的 ToolPlan。

Steps：

- `tool_calls.extract`：从 ctx.current_model_response 取出 tool_calls 列表
- `tool_calls.parse_arguments`：将 JSON string arguments 解析为 dict；解析失败时标记该 call 为 error
- `tool_calls.validate_schema`：校验参数是否符合工具的 parameters_schema
- `tool_calls.resolve_tools`：确认每个工具存在于 before_agent 阶段 snapshot 的 available_tools 中；不存在则标记 error
- `tool_plan.build_serial`：构建串行执行计划，保持模型返回的顺序
- `approval.prepare_requests`：识别哪些 call 需要审批，构建审批上下文（第一版只做标记，真正阻断在 tool_call middleware）

### 3.4 tool_call

结构：

```
tool_call:
  middleware:
    - approval.guard
    - audit.record
    - result_limit.guard
  action:
    - tools.dispatch_serial
```

- `approval.guard`：根据 ctx.current_tool_plan 判断是否需要审批；如果拒绝，生成 denied 类型 tool result，skip actual dispatch
- `audit.record`：记录工具执行开始、结束、耗时、风险等级
- `result_limit.guard`：统一限制工具结果大小，截断过长内容
- `tools.dispatch_serial`：按 ToolPlan 顺序执行工具，每个工具调用 ToolDispatcher

AgentRunner 自动记录 runtime checkpoint：

- tool_call_started
- tool_call_completed / tool_call_failed

### 3.5 after_tool steps

after_tool 的完整职责定义：

> 把工具执行结果提交为下一轮 ReAct 可见的 observation。

Steps：

- `tool_results.capture`：收集执行结果到 ctx.current_tool_results
- `message.commit_tool_results`：将每个 tool result 作为 role=tool message 加入 message list，保留 tool_call_id 对应关系

说明：

- 不在 after_tool 做上下文压缩；压缩/裁剪放到下一轮 before_model 的 context.prepare_with_budget

### 3.6 ReAct 循环闭合

- AgentRunner 在 after_tool 完成后，回到 before_model 开始下一轮 iteration
- 下一轮 messages.collect_visible 能看到：
  - 上一轮的 assistant message（含 tool_calls）
  - 上一轮的 tool result messages
- 循环直到模型返回无 tool_calls 的 response（result.detect_final_answer 设置 final_result）

### 3.7 before_agent step 实现

- `tools.snapshot_available_tools`：从 ToolRegistry 获取所有已注册工具的 schema，写入 ctx.base_model_context.available_tools

### 3.8 内置工具：think

- 无副作用的思考工具
- 参数：thought（字符串）
- 返回：原样返回 thought 内容
- 用途：让模型有显式思考空间，同时验证工具调用通路端到端可用

## Todo List

| # | 任务 | 状态 |
|---|------|------|
| 3.1 | 定义 `ToolSpec` 数据结构 | done |
| 3.2 | 定义 `ToolCall` 数据结构 | done |
| 3.3 | 定义 `ToolResult` 数据结构（success / error / denied） | done |
| 3.4 | 定义 `ToolPlan` 数据结构 | done |
| 3.5 | 实现 `ToolRegistry`（register / get / list_schemas） | done |
| 3.6 | 实现 `ToolDispatcher`（串行执行 + 防御性校验 + 异常捕获） | done |
| 3.7 | 实现 step `tool.detect_requested`（after_model 补充） | done |
| 3.8 | 实现 step `tool_calls.extract` | done |
| 3.9 | 实现 step `tool_calls.parse_arguments` | done |
| 3.10 | 实现 step `tool_calls.validate_schema` | done |
| 3.11 | 实现 step `tool_calls.resolve_tools` | done |
| 3.12 | 实现 step `tool_plan.build_serial` | done |
| 3.13 | 实现 step `approval.prepare_requests`（标记需审批的工具） | done |
| 3.14 | 实现 tool_call action `tools.dispatch_serial` | done |
| 3.15 | 实现 middleware `approval.guard`（含 denied result 生成） | done |
| 3.16 | 实现 middleware `audit.record` | done |
| 3.17 | 实现 middleware `result_limit.guard`（截断过长结果） | done |
| 3.18 | 实现 step `tool_results.capture` | done |
| 3.19 | 实现 step `message.commit_tool_results`（加入内存 message list） | done |
| 3.20 | 实现 before_agent step `tools.snapshot_available_tools`（真实逻辑） | done |
| 3.21 | 实现内置工具 `think` | done |
| 3.22 | 验证 ReAct 多轮循环闭合（messages 正确累积） | done |
| 3.23 | 编写集成测试：单轮工具调用 → 最终回答 | done |
| 3.24 | 编写集成测试：多轮工具调用 → 最终回答 | done |
| 3.25 | 编写单元测试：审批拒绝 → denied result → 模型继续 | done |
| 3.26 | 编写单元测试：工具不存在 / 参数校验失败 → error result | done |

## 交付与验收标准

- [x] 模型请求 think 工具 → 执行 → 结果回到上下文 → 模型基于结果继续推理
- [x] 多轮 ReAct 正确循环直到最终回答
- [x] 审批拒绝时生成 denied result，模型收到后调整策略（不终止 AgentRun）
- [x] result_limit.guard 能截断过长的工具结果
- [x] 工具不存在时产生 error 类型 tool result（不抛异常）
- [x] 参数校验失败时产生 error 类型 tool result
- [x] messages.collect_visible 能正确包含前轮 assistant tool_calls + tool results
- [x] tools.snapshot_available_tools 正确从 ToolRegistry 获取 schema
- [x] 所有测试通过
