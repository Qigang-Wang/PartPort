# PartPort：KiCad 10 原理图插件实施方案

## 1. 目标与结论

把现有 `jlc2kicad_gui.py` 改造成 KiCad 10 IPC API 插件，使用户可在原理图编辑器工具栏中启动 PartPort，输入 LCSC 编号并将符号、封装和 3D 模型导入当前工程。

结论：目标可行，但必须区分两个层级：

- KiCad 10 可以通过 IPC 插件动作的 `schematic` scope，在原理图编辑器中显示并启动插件。
- KiCad 10 尚不提供完整、稳定的原理图对象 IPC API。因此 v1 可以导入和注册工程库，但不要承诺自动把新符号放到画布上，也不要依赖 API 强制刷新原理图库。

v1 的定义是“从原理图编辑器启动的工程库导入器”，不是“自动放置原理图符号的编辑器自动化插件”。

## 2. 已验证环境

开发机当前环境：

- KiCad：10.0.4
- KiCad 自带 Python：3.11.5
- KiCad 自带 wxPython：4.2.2
- KiCad 自带 Python 不包含 `_tkinter`，所以现有 Tkinter UI 不能直接运行在 KiCad 管理的 Python 插件环境中。
- 系统 Python 3.13 包含 Tkinter，且当前 `JLC2KiCadLib.exe` 位于用户 Python 3.13 的 Scripts 目录；插件不得依赖这个用户私有绝对路径。
- KiCad 10 IPC 插件目录（Windows）：`%USERPROFILE%\Documents\KiCad\10.0\plugins\<plugin-id>\`。
- 已按 KiCad 的 `venv --system-site-packages` 和 `pip --only-binary :all:` 方式做过冒烟测试；`JLC2KiCadLib==1.2.3`、`kicad-python==0.7.1` 与 KiCad 自带 wxPython 可以在同一虚拟环境中成功导入，JLC2 CLI 也可执行。

因此 v1 使用 KiCad 自带的 wxPython 重写 GUI，不在 `requirements.txt` 中安装另一个 wxPython，也不继续使用 Tkinter。

## 3. 参考项目结论

### 3.1 TousstNicolas/JLC2KiCad_lib

参考版本：提交 `48d36032108d64b0f59755234681f1ce8bc98d46`，PyPI 版本 `1.2.3`。

采用的能力：

- 已有稳定 CLI，可由一个或多个 `Cxxxxx` 编号生成 `.kicad_sym`、`.kicad_mod`、STEP 和 WRL。
- 支持 `-dir`、`-symbol_lib`、`-symbol_lib_dir`、`-footprint_lib`、`-model_dir`、`-model_base_variable`、`--skip_existing` 等参数。
- 符号更新、封装生成和 3D 模型路径拼装已经由该项目处理。
- MIT 许可证，适合作为外部依赖使用。

注意事项：

- CLI 的网络请求没有统一超时控制；PartPort 必须给每个子进程设置总超时并支持取消。
- 某些逻辑错误只写日志，进程退出码不一定能完整代表导入成功；PartPort 必须同时检查退出码、日志关键字和实际输出文件。
- 不调用当前用户目录中的 `JLC2KiCadLib.exe`。应在 KiCad 创建的插件虚拟环境中安装固定版本，然后使用 `sys.executable -m JLC2KiCadLib.JLC2KiCadLib` 调用。
- 不直接调用该项目未声明为公共 API 的内部函数，降低升级耦合。

### 3.2 hulryung/kicad-lcsc-manager

参考版本：提交 `2430b2ccf184d2d4ce99452959d8ac3739a5785c`。

值得采用的设计：

- 工程专用库放在工程目录，并使用 `${KIPRJMOD}` 生成可移植 URI。
- 使用 wxPython 构建 KiCad 风格 GUI。
- 下载和预览采用后台任务，GUI 更新回到 wx 主线程。
- 提供全局配置、工程覆盖配置、导入选项、缓存、进度和结果摘要。
- 对符号、封装和 3D 模型分别报告结果，允许部分失败。
- BOM 批量导入、搜索、预览可作为 PartPort 后续版本方向。

明确不照搬的部分：

- 该项目使用传统 `pcbnew.ActionPlugin`，入口只能位于 PCB Editor，不满足本项目的原理图入口目标。
- 不在后台线程调用 `pcbnew`/KiCad GUI API；KiCad GUI 与 IPC 调用都应视为主线程敏感操作。
- 不使用 `rstrip(')')` 加字符串拼接的方式修改 `sym-lib-table` 或 `fp-lib-table`，这会破坏嵌套或未来格式。
- 不复制其 vendored `easyeda2kicad.py` 转换代码。该部分含 AGPL-3.0 来源；PartPort v1 保持以 MIT 的 `JLC2KiCadLib` 为外部转换依赖，避免不必要的许可证和维护负担。
- 不创建虚假的占位 3D 模型；不存在模型时应明确报告“无模型”，不能把占位物当作成功下载结果。

参考链接：

- https://github.com/TousstNicolas/JLC2KiCad_lib
- https://github.com/hulryung/kicad-lcsc-manager
- https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
- https://go.kicad.org/api/schemas/v1
- https://docs.kicad.org/kicad-python-main/kicad.html

## 4. 选择的技术架构

采用“KiCad 10 IPC Python action + 独立 wxPython GUI + JLC2KiCadLib 子进程”的结构。

```text
KiCad 10 Schematic Editor
        |
        | plugin.json / scopes=["schematic"]
        v
partport_plugin.py（独立 Python 进程）
        |
        +-- KiCadContext：通过 KICAD_API_SOCKET/TOKEN 查找当前原理图/工程
        +-- wx UI：输入、选项、进度、日志、取消
        +-- ImportService：校验、排队、备份、结果汇总
        +-- JLC2Runner：逐个启动 JLC2KiCadLib 子进程
        +-- LibraryTableManager：原子更新工程库表
        v
<project>/PartPortLib/
```

不选择以下方案：

- Tkinter + KiCad Python：本机已验证缺少 `_tkinter`。
- Tkinter + PyInstaller `exec` 插件：可行但包体大、平台相关、重复携带 Python，作为备用方案而非 v1。
- SWIG `pcbnew.ActionPlugin`：只能从 PCB Editor 启动且已弃用。
- KiCad HTTP Library：适合元数据/ERP 检索，但不能替代本地生成任意符号和封装的流程。
- 在 v1 中直接修改 `.kicad_sch`：风险高，也绕开 KiCad 的撤销和缓存机制。

## 5. 建议目录结构

```text
PartPort/
├── AGENTS.md
├── README.md
├── LICENSE
├── plugin.json
├── requirements.txt
├── partport_plugin.py
├── partport/
│   ├── __init__.py
│   ├── app.py                 # wx.App 和主窗口
│   ├── input_parser.py        # LCSC 编号及 URL 规范化
│   ├── kicad_context.py       # IPC 连接、工程检测、配置目录
│   ├── import_service.py      # 业务编排和批量结果
│   ├── jlc2_runner.py         # 子进程、日志、超时、取消
│   ├── library_tables.py      # 工程库表的安全读写
│   ├── settings.py            # 全局/工程设置
│   ├── validation.py          # 输出文件检查
│   └── models.py              # dataclass/枚举
├── resources/
│   ├── icon-light.png
│   └── icon-dark.png
├── scripts/
│   ├── install-dev.ps1
│   └── uninstall-dev.ps1
└── tests/
    ├── test_input_parser.py
    ├── test_project_context.py
    ├── test_library_tables.py
    ├── test_runner.py
    └── fixtures/
```

现有 `jlc2kicad_gui.py` 在迁移期间保留，直到 wx UI 与共享业务层通过验收。不要在第一步直接删除它。

## 6. 插件清单

`plugin.json` 使用 KiCad IPC 插件 schema，v1 只注册原理图动作：

```json
{
  "$schema": "https://go.kicad.org/api/schemas/v1",
  "identifier": "com.partport.kicad10",
  "name": "PartPort",
  "description": "Import LCSC/EasyEDA symbols, footprints and 3D models into the current project",
  "runtime": {
    "type": "python",
    "min_version": "3.9"
  },
  "actions": [
    {
      "identifier": "import-lcsc-part",
      "name": "Import LCSC Part",
      "description": "Download an LCSC/EasyEDA part into this KiCad project",
      "show-button": true,
      "scopes": ["schematic"],
      "entrypoint": "partport_plugin.py",
      "icons-light": ["resources/icon-light.png"],
      "icons-dark": ["resources/icon-dark.png"]
    }
  ]
}
```

`requirements.txt` 初始固定版本：

```text
JLC2KiCadLib==1.2.3
kicad-python==0.7.1
```

规则：

- 不把 `wxPython` 写入 requirements；使用 KiCad 自带版本。
- KiCad 10 会用 `--system-site-packages` 创建插件虚拟环境并从 `requirements.txt` 安装二进制依赖。
- 每次升级依赖前，先用 KiCad 10.0.4 的“Recreate Plugin Environment”重建并跑回归测试。
- 插件首次加载时依赖安装可能需要一段时间；UI/README 必须说明工具栏图标不会立即出现。

## 7. 当前工程识别

插件不能硬编码输出目录，也不能假设工作目录就是工程目录，因为 KiCad 启动 action 时将工作目录设为插件目录。

解析顺序：

1. 用 `kipy.KiCad()` 读取 KiCad 自动提供的 `KICAD_API_SOCKET` 与 `KICAD_API_TOKEN`。
2. 调用 `get_open_documents(DOCTYPE_SCHEMATIC)`，读取打开的原理图文档路径。
3. 只有一个有效文档时，取其父目录作为候选工程目录。
4. 优先寻找同名 `.kicad_pro`；否则在目录内寻找唯一 `.kicad_pro`。
5. 没有结果、存在多个结果、原理图未保存或 IPC 失败时，显示目录选择器，不应直接失败。
6. GUI 始终显示解析后的绝对工程路径，并允许用户手动更改。
7. 多个原理图编辑器同时打开时不得任意选择第一个文档，必须让用户确认。

KiCad 10 的 IPC 只用于上下文发现和插件配置目录，不用于原理图对象 CRUD。

## 8. 输入与 UI

v1 保留现有 GUI 的核心能力并补齐工程语义：

- 多行输入，支持逗号、分号、空格和换行。
- 编号统一转为大写，只接受 `^C\d+$`，按首次出现顺序去重。
- 可以粘贴包含 `Cxxxxx` 的 LCSC、JLCPCB 或 `item.szlcsc.com` URL；从文本中提取编号。
- 如果 URL 本身不含 `Cxxxxx`，v1 明确提示用户填写 LCSC 编号，不在首版依赖易变的网页 HTML 抓取。
- 显示当前工程、符号库、封装库和模型目录的预览。
- 选项：符号、封装、STEP、WRL、遇到已有文件时跳过/更新。
- 安全默认值：导入符号、封装和 STEP；已有内容默认“跳过”。
- 日志区显示每个编号的状态；批量任务完成后给出成功、跳过、失败列表。
- 只允许一个活动导入任务；支持取消当前子进程并停止后续队列。
- 网络和转换工作在后台线程；所有 wx 控件更新必须使用事件或 `wx.CallAfter` 回到主线程。

搜索、价格、库存、SVG 预览和 BOM 导入放到 v2，不阻塞 v1 上线。

## 9. 工程库布局与 JLC2KiCadLib 参数

默认输出布局：

```text
<project>/PartPortLib/
├── symbols/
│   └── partport.kicad_sym
└── partport.pretty/
    ├── *.kicad_mod
    └── packages3d/
        ├── *.step
        └── *.wrl
```

库表昵称：

- 符号库：`partport`
- 封装库：`partport`

逐个元件调用，便于精确显示进度、取消和隔离失败：

```text
<plugin-venv-python> -m JLC2KiCadLib.JLC2KiCadLib Cxxxx \
  -dir <project>/PartPortLib \
  -symbol_lib partport \
  -symbol_lib_dir symbols \
  -footprint_lib partport.pretty \
  -model_dir packages3d \
  -model_base_variable ${KIPRJMOD}/PartPortLib/partport.pretty \
  -models STEP \
  --skip_existing
```

实现规则：

- 必须以参数数组启动，禁止 `shell=True`，禁止拼接 shell 命令字符串。
- 使用 `sys.executable`，确保转换器运行在当前插件虚拟环境。
- `--skip_existing` 对应默认安全模式；用户明确选择“更新”时才移除此参数。
- 每个编号有可配置总超时，建议默认 180 秒；超时后终止子进程并报告。
- stdout/stderr 逐行读入线程安全队列；不要等待进程结束后才一次性显示。
- Windows 终止时先正常 terminate，短暂等待后再 kill；退出插件时不得留下子进程。
- 每个元件开始前记录/备份 `partport.kicad_sym`、可能被更新的同名封装和模型；失败、超时、取消或验证不通过时恢复旧文件，并删除本次产生的不完整新文件。
- 批量开始前另行备份相关库表；任何失败都不能删除已有有效数据。

## 10. 工程库表管理

首次导入时写入工程目录的库表：

`sym-lib-table`：

```text
(lib (name "partport")(type "KiCad")(uri "${KIPRJMOD}/PartPortLib/symbols/partport.kicad_sym")(options "")(descr "PartPort imported symbols"))
```

`fp-lib-table`：

```text
(lib (name "partport")(type "KiCad")(uri "${KIPRJMOD}/PartPortLib/partport.pretty")(options "")(descr "PartPort imported footprints"))
```

安全要求：

- 精确解析顶层 S-expression 和每个库条目的 `name`/`uri`，不能用昵称的普通子串搜索。
- 保留未知字段、注释、嵌套表和原有顺序。
- 如果昵称已存在但 URI 不同，停止自动修改并显示冲突解决对话框；不能静默覆盖用户配置。
- 写入前创建备份，写入临时文件，重新解析校验后用 `os.replace` 原子替换。
- 处理 CRLF/LF、UTF-8、空表和文件不存在的情况。
- 对同一工程使用进程锁，避免两个 PartPort 实例同时修改库和库表。
- 首次新增库表条目后明确提示用户关闭并重新打开原理图编辑器。KiCad 10 没有稳定的原理图库刷新 IPC API，不能假装刷新已成功。

## 11. 输出验证与成功判定

不能只看子进程退出码。每个元件至少执行以下检查：

- `.kicad_sym` 存在、非空、括号平衡且以 `kicad_symbol_lib` 开头。
- 符号库中可找到本次 LCSC 元件对应的属性或本次日志报告的符号名。
- 请求封装时至少生成或确认存在对应 `.kicad_mod`。
- `.kicad_mod` 非空、括号平衡，并包含至少一个 pad；无 pad 的特殊器件只能作为显式警告接受。
- 请求 STEP/WRL 时验证文件存在、非空；远端无模型应标记为“不可用”，不是整个符号/封装导入失败。
- 封装中的 `(model ...)` 路径必须使用 `${KIPRJMOD}`，并能解析到实际文件。
- 库表写回后重新解析，确认 `partport` 昵称指向预期 URI。

批量结果状态使用：`success`、`partial`、`skipped`、`failed`、`cancelled`，不要只用布尔值。

## 12. 配置、日志与缓存

全局设置优先使用 `KiCad.get_plugin_settings_path("com.partport.kicad10")` 返回的目录。工程级覆盖文件使用：

```text
<project>/.partport.json
```

配置优先级：默认值 < 全局设置 < 工程设置。

工程设置只保存可移植的相对路径和选项；不要保存开发机的 Python 或 `JLC2KiCadLib.exe` 绝对路径。

日志要求：

- GUI 显示当前会话日志。
- 持久日志按大小轮转，不无限增长。
- 记录插件版本、KiCad/Python 版本、编号、命令参数、退出码和验证结果。
- 不记录 KiCad API token，不输出完整环境变量。
- 失败对话框给出日志位置和可操作建议。

v1 可不实现网络响应缓存，因为 `JLC2KiCadLib` 是外部后端；v2 做搜索/预览时再增加带过期时间的缓存。

## 13. 实施阶段

### 阶段 A：最小插件入口

- 添加 `plugin.json`、空 `requirements.txt` 测试版、图标和 `partport_plugin.py`。
- 在 KiCad 10.0.4 开启 Preferences > Plugins > API server。
- 验证动作只在 Schematic Editor 工具栏出现且可重复启动/退出。
- 验证 stdout/stderr 错误能在 KiCad 状态栏警告系统中看到。

完成标准：从原理图编辑器点击图标能打开一个最小 wx 窗口。

### 阶段 B：业务层拆分与 wx GUI

- 从 `jlc2kicad_gui.py` 提取输入解析、任务状态和日志模型。
- 实现 wx GUI，但暂不删除 Tkinter 版本。
- 完成工程自动检测与手动选择回退。

完成标准：不联网也能验证输入、工程路径、任务队列和取消状态。

### 阶段 C：转换器集成

- 固定 `JLC2KiCadLib==1.2.3`。
- 实现逐元件子进程、实时日志、超时和取消。
- 实现符号/封装/模型的结果验证与部分失败状态。

完成标准：至少用 `C393941` 和一组有/无 3D 模型的回归元件生成有效文件。

### 阶段 D：工程库注册

- 实现安全的 S-expression 表更新、备份、冲突检测和原子写入。
- 注册 `${KIPRJMOD}` URI。
- 显示第一次导入后的重启/重开提示。

完成标准：关闭并重开原理图后，可在 Symbol Chooser 中找到 `partport` 符号；其 footprint 和 3D model 路径有效。

### 阶段 E：打包和安装

- 添加开发安装/卸载脚本，使用目录联接或复制到 KiCad 10 plugins 目录。
- 测试全新插件虚拟环境创建和 requirements 安装。
- 生成版本化 ZIP 和校验和。
- 首发采用手工安装或自定义 PCM repository；不要假设能进入官方 PCM。直接连接 LCSC/JLCPCB 商业服务可能受 KiCad 官方 addon 商业服务政策限制。

完成标准：在一台没有系统级 `JLC2KiCadLib.exe` 的 Windows 机器上，仅靠插件包即可安装运行。

### 阶段 F：后续增强（不属于 v1）

- LCSC/JLCPCB 关键词搜索、库存和价格。
- EasyEDA SVG 符号/封装预览与缓存。
- BOM CSV/XLSX 批量导入。
- 全局/工程路径设置 UI。
- Linux/macOS 验证。
- KiCad 11 原理图 API 成熟后，再评估自动打开 Symbol Chooser 或放置符号。

## 14. 测试矩阵

单元测试：

- 混合分隔符、重复编号、大小写、非法编号和含编号 URL。
- 无/单个/多个打开文档的工程上下文解析。
- 空库表、已有正确条目、昵称冲突、嵌套表、CRLF 和损坏表。
- 子进程成功、非零退出、无输出、超时、取消和逻辑失败但退出码为 0。
- `${KIPRJMOD}` URI 与磁盘路径的一致性。

集成测试：

- 新工程首次导入。
- 已有 `sym-lib-table`/`fp-lib-table` 的工程。
- 已有元件的跳过与显式更新。
- 路径包含空格、中文和非 ASCII 字符。
- 远端无符号、无封装、无 3D 模型和网络限流。
- 批量任务中间失败后继续处理后续编号。

手工 KiCad 10.0.4 验收：

1. 工具栏按钮位于 Schematic Editor。
2. 插件识别当前保存的工程。
3. 导入过程不冻结 KiCad 或插件 GUI。
4. 取消后无残留转换进程。
5. 重开原理图后能找到符号。
6. 放置符号后 footprint 链接到 `partport:<footprint>`。
7. PCB 3D Viewer 能加载 `${KIPRJMOD}` 下的模型。

## 15. 开发约束

- 先实现 v1 的编号导入闭环，再做搜索、预览和 BOM。
- UI、业务层、KiCad 上下文、子进程和文件写入必须分离，便于无 KiCad 环境下测试。
- 禁止硬编码用户目录、KiCad 安装目录、Python 版本和 `JLC2KiCadLib.exe` 路径。
- 禁止从工作线程直接更新 wx 控件或调用 KiCad API。
- 禁止直接修改 `.kicad_sch`、`.kicad_pro` 或全局库表。
- 工程库表和已有库文件属于用户数据；所有破坏性更新必须可恢复。
- 不复制 AGPL 来源的转换实现，除非项目明确决定整体满足 AGPL 分发义务。
- 生成内容必须提示用户核对引脚编号、封装尺寸、焊盘和 3D 对齐；外部库转换结果不能视为已经过工程验证。

## 16. v1 最终验收定义

只有同时满足以下条件，才算迁移完成：

- PartPort 是有效的 KiCad 10 IPC Python 插件，而不是传统 `pcbnew.ActionPlugin`。
- 可从 Schematic Editor 工具栏启动。
- 不依赖 Tkinter、系统 Python 或用户预装的 `JLC2KiCadLib.exe`。
- 能自动识别或让用户确认当前工程目录。
- 能批量导入 LCSC 编号并实时显示日志、取消、超时和逐项结果。
- 符号、封装和 3D 模型写入工程内的可移植目录。
- 工程库表以安全、原子、可恢复的方式注册 `${KIPRJMOD}` URI。
- 重开原理图后，符号、footprint link 和 3D model 均可在 KiCad 中实际使用。
- 自动化测试覆盖解析、库表、执行器和失败路径。
- README 给出安装、首次依赖创建、API server、刷新限制、卸载和故障排查说明。

## 17. 用户追加范围：全局库配置页

在 v1 工程本地库保持默认值的基础上，增加 `Settings` 页面：

- 目标模式可选“工程本地 PartPort 库”或“已有全局库”。
- 从 KiCad 10 全局 `sym-lib-table` 和 `fp-lib-table` 读取候选项，符号库与封装库分别选择。
- 只允许已有、可写、`type=KiCad` 的文件库；禁止写入 KiCad 安装目录和 `type=Table` 的官方聚合库。
- 不修改全局库表本身。全局模式只向用户已经注册的库文件合并内容。
- 转换器始终先写入临时目录；验证成功后才合并符号、封装和模型。
- 合并符号时将 footprint link 改为所选全局封装库昵称；模型路径改为所选 footprint URI 下的 `packages3d`。
- 覆盖已有文件前生成 `.partport.bak`，写文本文件时继续使用临时文件加 `os.replace`。
- 配置持久化不得保存 Python、API token 或 `JLC2KiCadLib.exe` 路径。

## 18. 用户追加范围：界面语言与模型路径

- `Settings` 页面提供中文和 English 两种界面语言，选择结果写入同一配置文件。
- PartPort 自身的窗口、按钮、校验结果和提示信息随语言切换；外部 JLC2KiCadLib 原始日志不翻译。
- 为避免运行中重建全部 wx 控件，保存语言后提示用户重新打开 PartPort 生效。
- 设置页始终显示解析后的 3D 模型保存位置。
- 工程模式默认位置为 `${KIPRJMOD}/PartPortLib/partport.pretty/packages3d`。
- 全局模式默认位置为所选全局 footprint `.pretty` 目录内的 `packages3d`。
- 全局库模式不依赖工程路径，导入页隐藏整个工程目录选择区域；切回工程本地模式时恢复显示。

## 19. 用户追加范围：搜索工作台与多数据源

- 工程目录选择从导入页完全移入 `Settings` 页面；全局库模式下禁用该输入。
- 设置页的数据来源使用独立复选框，可选 `LCSC.com`、`SZLCSC.com`，允许单选或多选，但禁止全部取消后保存。
- LCSC 公共目录接口承担关键词、型号和 C 编号的分页检索；SZLCSC 商品详情页提供中文名称、品牌、库存、价格和图片。两个商城共用 LCSC code/product id，结果按 C 编号统一。
- 数据来源表示商城目录和商品元数据来源。CAD 符号、封装 SVG 与转换输入来自该 C 编号关联的 EasyEDA/立创EDA 器件记录，设置页必须明确说明这一点。
- 主页面顶端是单行搜索栏；中间用 splitter 分为左侧结果表和右侧详情区；详情区包含资料、原理图、封装、零件图片四个页签。
- 符号和封装页只显示净化后的 EasyEDA 来源 SVG，不提供“KiCad 输出”模式、来源切换器或相关状态文字。
- 页面底部集中显示 Symbol、Footprint、STEP、WRL、跳过已有器件和下载导入按钮；不再保留大面积编号输入框。
- 日志改为默认折叠的小型活动区；失败、取消和导入完成时可展开，不再占据主页面主体。
- 搜索和详情请求必须在工作线程执行，使用 generation token 丢弃过期结果；工作线程仍不得直接操作 wx 控件。

## 20. 用户追加范围：来源预览与零件图片

- 选择搜索结果后，符号和封装页立即显示已净化的 EasyEDA 来源 SVG；禁止为了二维预览在后台执行 `kicad-cli sym export svg`、`kicad-cli fp export svg` 或生成 KiCad 二维缓存。
- 搜索结果选择不得触发符号转换。正式的符号和封装转换仅在用户点击“下载并导入”后执行。
- “零件图片”页显示所选商城记录提供的商品图片，不再生成或展示 STEP/WRL 渲染图，并删除没有数据来源的“检查结果”页。
- 选择搜索结果不得启动 JLC2KiCadLib、`kicad-cli` 或其他 CAD 转换子进程；STEP/WRL 仅在用户点击“下载并导入”且勾选对应格式时生成。
- 符号、封装和零件图片的内嵌预览提供缩小、重置、放大按钮；鼠标位于预览内容上时直接使用滚轮缩放，无需按 Ctrl，并继续支持 `Ctrl + +/-/0`；SVG 符号和封装在 100% 时自动适合预览区宽度，窗格尺寸变化后重新适配；缩放工具栏不随内容一起缩放。
- 所有远端 SVG 在进入 wx WebView 前删除脚本、事件处理器、`foreignObject` 和外部资源链接；预览 HTML 使用限制性的 Content Security Policy。
- 独立进程原生窗口不得通过 Windows `SetParent` 冒充稳定的 PartPort 子控件；跨进程嵌入存在窗口样式、焦点、DPI、缩放、销毁顺序和崩溃隔离问题。未来需要交互式 3D 时，优先使用同进程 `wxGLCanvas` 或 WebView/WebGL 查看器。
