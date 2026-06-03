# 第七步：内置工具补全

## 环节定位

L-Agent 实施计划的第七步。在工具调用通路和 CLI 交互都就绪的基础上，补全日常开发场景所需的内置工具集。每个工具遵循统一的 ToolSpec 规范。

## 注意事项

- 每个工具必须有完整的 ToolSpec（name / description / parameters_schema）
- 工具错误处理统一格式，不抛异常到 AgentRunner，而是返回 error 类型的 ToolResult
- terminal 工具有副作用，默认需要审批；read_file 等只读工具可以配置 auto-approve
- result_limit.guard 对所有工具结果生效，工具实现不需要自行截断
- 工具实现应尽量薄，核心逻辑通过标准库或轻量依赖完成
- web_search / web_fetch 需要考虑网络不可用时的错误处理
- 工具的 description 和 parameters_schema 直接影响模型调用质量，需要精心设计

## 详细内容

### 7.1 文件操作工具

**read_file**：

- 参数：file_path（必需）、offset（可选，起始行）、limit（可选，读取行数）
- 返回：文件内容（带行号）
- 错误：文件不存在、权限不足、路径非法
- 审批：auto-approve（只读操作）

**write_file**：

- 参数：file_path（必需）、content（必需）
- 返回：写入成功确认
- 错误：路径非法、权限不足、磁盘空间不足
- 审批：需要确认（有副作用）

**list_directory**：

- 参数：path（必需）、recursive（可选，默认 false）、pattern（可选，glob 过滤）
- 返回：文件/目录列表
- 错误：路径不存在、权限不足
- 审批：auto-approve（只读操作）

**search_file**：

- 参数：pattern（必需，搜索内容）、path（可选，搜索范围）、file_pattern（可选，文件名过滤）
- 返回：匹配结果（文件名 + 行号 + 内容）
- 错误：pattern 非法、路径不存在
- 审批：auto-approve（只读操作）

### 7.2 终端工具

**terminal**：

- 参数：command（必需）、timeout（可选，默认 120 秒）、cwd（可选，工作目录）
- 返回：stdout + stderr + exit_code
- 错误：命令超时、执行失败
- 审批：默认需要确认（高风险）
- 特殊处理：限制命令执行时间，避免阻塞 Agent

### 7.3 Web 工具

**web_search**：

- 参数：query（必需）、limit（可选，结果数量）
- 返回：搜索结果列表（title / url / snippet）
- 错误：网络不可用、搜索服务异常
- 审批：auto-approve（只读操作）
- 依赖：需要搜索 API 配置

**web_fetch**：

- 参数：url（必需）
- 返回：页面内容（转为文本/markdown）
- 错误：网络不可用、URL 无效、超时
- 审批：auto-approve（只读操作）

### 7.4 工具统一规范

每个工具实现必须：

1. 定义完整 ToolSpec（name / description / parameters_schema）
2. handler 签名统一：`(arguments: dict) -> str`
3. 所有异常内部捕获，返回 error 描述字符串
4. 不依赖全局状态，参数自包含
5. description 清晰描述工具用途和适用场景（模型可见）
6. parameters_schema 使用 JSON Schema 格式，包含 required 字段标注

### 7.5 审批策略配置

默认审批策略：

```yaml
approval:
  auto_approve:
    - think
    - read_file
    - list_directory
    - search_file
    - web_search
    - web_fetch
  always_confirm:
    - terminal
    - write_file
```

## Todo List

| # | 任务 | 状态 |
|---|------|------|
| 7.1 | 实现 `read_file` 工具（含 offset/limit 参数） | done |
| 7.2 | 实现 `write_file` 工具 | done |
| 7.3 | 实现 `list_directory` 工具（含 recursive/pattern） | done |
| 7.4 | 实现 `search_file` 工具（grep 能力） | done |
| 7.5 | 实现 `terminal` 工具（含超时控制） | done |
| 7.6 | 实现 `web_search` 工具 | done |
| 7.7 | 实现 `web_fetch` 工具（HTML → text/markdown） | done |
| 7.8 | 为每个工具定义完整 parameters_schema（JSON Schema） | done |
| 7.9 | 为每个工具编写精确的 description（影响模型调用质量） | done |
| 7.10 | 统一错误处理：所有异常内部捕获，返回结构化错误 | done |
| 7.11 | 配置工具默认审批策略 | done |
| 7.12 | 编写 read_file 单元测试 | done |
| 7.13 | 编写 write_file 单元测试 | done |
| 7.14 | 编写 list_directory 单元测试 | done |
| 7.15 | 编写 search_file 单元测试 | done |
| 7.16 | 编写 terminal 单元测试（含超时） | done |
| 7.17 | 编写 web_search 单元测试 | done |
| 7.18 | 编写 web_fetch 单元测试 | done |
| 7.19 | 编写端到端测试：多工具协作完成开发任务 | done |

## 交付与验收标准

- [x] 能用 L-Agent 读写文件（read_file / write_file）
- [x] 能用 L-Agent 执行 shell 命令（terminal）
- [x] 能用 L-Agent 搜索文件内容（search_file）
- [x] 能用 L-Agent 搜索 web 信息（web_search / web_fetch）
- [x] 工具结果正确回到模型上下文，驱动多步任务完成
- [x] 每个工具的 schema 能被模型正确理解和调用
- [x] 工具执行错误时返回结构化错误信息，模型能据此调整策略
- [x] terminal 工具默认需要审批，只读工具可 auto-approve
- [x] 大结果被 result_limit.guard 正确截断
- [x] terminal 超时正确处理（不阻塞 Agent）
- [x] 所有测试通过
