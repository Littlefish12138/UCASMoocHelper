# UCAS 慕课挂课工具

基于 CDP（Chrome DevTools Protocol）的自动化挂课工具，专为中国科学院大学 MOOC 平台设计。

---

## 组成与实现

### 主要代码功能

- **CDP 协议控制浏览器**：无需 `drivers.exe`，通过调试端口直接操控 Edge / Chrome。
- **灵活启动模式**：
  - 自动启动（指定用户数据目录，可使用登录状态）
  - 无痕模式启动
  - 连接已打开调试端口的现有浏览器
- **配置驱动元素定位**：通过 JSON 声明页面元素的查找方式与数据提取规则，页面结构变化时只需修改配置文件，无需改动核心代码。

### 主要类与功能

#### `CourseHandler`

课程任务处理器，封装了以下核心方法：

| 方法                | 说明                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------- |
| `finish_video`      | 完成单个视频任务：监控视频播放状态，若被暂停自动恢复，直到任务完成或超时。                        |
| `finish_questions`  | 完成单个视频的章节测试题：读取题目配置，匹配答案并自动勾选。                                      |
| `run_course_task`   | 根据 `only_unfinished`/ `video_needed` / `question_needed` 参数，批量处理课程树中所有视频及测试。 |
| `get_all_questions` | 遍历所有章节，抓取全部测试题的题干、选项、正确答案等信息，用于生成答案库。                        |

#### `ElementLocator`

配置驱动的树形元素查找器。通过 JSON 声明查找路径、数据字段和输出结构，可灵活适配不同页面布局，无需为每个网页单独编写解析代码。提供`extract_info()`方法

---

## 使用范围

> 当前 `CourseHandler` 的交互逻辑、判断条件（如“任务点已完成”的检测）是按照 **2025‑2026 秋季大一军事理论课** 的交互逻辑和UI实现的。
>
> - 如果课程平台的**交互流程**发生改变（例如按钮位置、点击顺序不同），需要修改 `CourseHandler` 中的对应逻辑。
> - 如果仅是**HTML 元素的 class / id / 属性**发生变化，只需修改对应的 JSON 配置文件`config.json`，无需改动 Python 代码。

---

## 操作方法

### 1. 下载 Release 中的 exe 程序直接运行

已经讲依赖全部打包到单个程序中，直接运行即可。

### 2. 图形界面

1.将mainwindow.ui和resources.qrc文件转换成ui_main.py文件和resources_rc.py文件，可以使用

```bash
pyside6-uic mainwindow.ui -o ui_main.py
pyside6-rcc resources.qrc -o resources_rc.py
```

2.运行 `main.py` 启动 GUI 窗口：

```
python main.py
```

- **课程链接**：粘贴课程的视频页面 URL。
- **启动模式**：
  - 自动启动：程序自动启动浏览器（可指定用户数据目录或无痕模式）。
  - 手动启动：连接到你已打开的调试端口浏览器（需先用命令行启动浏览器，如 `chrome.exe --remote-debugging-port=9222`）。
- **开始挂课**：点击后自动执行任务，日志输出到下方文本框。

### 3. 命令行 / 脚本调用

你可以自行编写调用逻辑，比如：

```python
from course_listener import CourseHandler
import utils
import json

# 启动浏览器
page = utils.launch_browser('edge',is_incognito=False)
page.get("课程URL")

# 加载配置文件
with open("页面配置json的路径", "r", encoding="utf-8") as f:
    elem_config = json.load(f)
with open("答案json路径", "r", encoding="utf-8") as f:
    answer_dict = json.load(f)

# 创建处理器并运行
handler = CourseHandler(page, elem_config, answers=answer_dict)
handler.run_course_task(only_unfinished = True, video_needed = True, question_needed = True)
```

### 3. 答案抓取与制作

使用 `get_all_questions` 方法可自动遍历所有章节的测试题，将结果保存为 JSON 文件。默认结构示意：

```json
{
  "46154": {
    "data": "46154",
    "stem": "【单选题】国防是阶级斗争的产物,它伴随着()的形成而产生。",
    "options": [
      {
        "name_and_content": "A、 军队"
      },
      {
        "name_and_content": "B、 生产力"
      },
      {
        "name_and_content": "C、 工人与农民"
      },
      {
        "name_and_content": "D、 阶级与国家"
      }
    ],
    "my_answer": "我的答案：D",
    "is_correct": "答案正确"
  },
  "46156": {
    "data": "46156",
    "stem": "【判断题】国防为国家和民族提供食物保障,并为国家和民族的利益服务。()",
    "my_answer": "我的答案：错",
    "is_correct": "答案正确"
  }
}
```

---

## 风险提示

1. **账号安全**：调试端口开启后，电脑上的**任意程序**都可以连接至该端口并操控浏览器，请务必确保在安全的环境下运行。
2. **平台更新**：若 MOOC 平台更新前端代码，配置文件可能失效，需要相应调整。
3. **学习目的**：本工具仅用于技术学习，请勿用于刷课、挂课、自动答题等行为，否则后果字符。
4. **法律责任**：使用者自行承担因违规使用而产生的一切后果。

---

## 常见问题

### Q1：无法正常启动浏览器/启动浏览器后没有反应？

- 使用用户数据目录启动时，确保先前没有浏览器实例占用
- 检查端口号是否冲突
- 使用Chrome时不允许使用默认数据目录，只能使用无痕模式或自行指定其他的用户数据目录

### Q2：已经看完视频/完成一节，但是网页上一直显示“任务点未完成”？

- 前端渲染有延迟，只要日志中显示播放完成即为后端认为播放完成，该视频已经完成。
- 如果播放视频时超时，检查网络是否稳定，视频能否正常播放。
- 可能平台前端的更新机制发生了变化，需要更新 `PageConfig.COMPLETE_IMAGE_KEYWORD` /页面配置json或者重写对应的逻辑。

### Q3：抓取章节测试题时某些选项内容缺失？

- 如果平台修改了选项的 HTML 结构，需要调整 `question_element.json` 中对应的 `locator`。
- 有些情况下，操作过快/页面加载较慢可能导致程序误判该章节没有章节测试题，可以适当调大 `PageConfig.PAGE_LOAD_TIME`

### Q4：如何修改配置文件以适配其他课程？

- 请阅读 `json配置规范v1.2.md`，按照规范编写对应课程的查找规则。
- 按照网页配置写一份`config.json`，查找器就能正常工作

### Q5：报错 `KeyNameConflict,KeyError`？

- 检查配置是不是写错了，键名冲突，虚拟容器键不存在之类的

---

## 依赖库和环境

- Python 3.8+
- DrissionPage >= 4.0.0
- PySide6
- Windows系统
- Edge/Chrome(理论上只要是Chromium内核的浏览器都行，但我没试过其他的)
