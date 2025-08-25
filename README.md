# 🤖 AI论文速览速学系统

> **让AI论文阅读变得简单高效，几分钟内掌握前沿技术要点**

`ai-paper-digest` 是一个专为AI研究者、工程师和学习者设计的智能论文摘要系统。它能够自动从RSS源获取最新AI论文，使用先进的AI模型（如DeepSeek、OpenAI兼容API、Ollama等）生成高质量的中文摘要，并提供现代化的Web界面帮助用户快速浏览和学习。

## ✨ 核心特性

### 🚀 智能论文处理
- **自动RSS抓取**：支持HuggingFace、ArXiv等主流AI论文源
- **AI驱动摘要**：使用先进的AI模型生成结构化的中文论文摘要
- **多LLM支持**：支持DeepSeek、OpenAI兼容API、Ollama等多种LLM提供商
- **智能标签系统**：自动提取论文主题标签，支持多级分类
- **并行处理**：多线程并发处理，批量生成摘要效率高

### 🌐 现代化Web界面
- **响应式设计**：支持桌面和移动设备
- **智能筛选**：基于标签和关键词的论文筛选
- **阅读进度跟踪**：记录已读论文，统计阅读数据
- **深色模式**：支持明暗主题切换
- **实时搜索**：快速定位感兴趣的论文

### 📚 结构化摘要内容
- **一句话总结**：快速理解论文核心贡献
- **创新点分析**：详细的技术创新点解析
- **实验结果**：关键指标和实际应用价值
- **术语表**：重要概念和缩写的解释

## 🏗️ 系统架构

```mermaid
graph TB
    %% RSS Feed Sources
    RSS[RSS源抓取<br/>collect_hf_paper_links_from_rss.py<br/>• HuggingFace Papers<br/>• ArXiv RSS<br/>• 自定义RSS源]
    
    %% Core Processing Pipeline
    SERVICE[服务编排<br/>feed_paper_summarizer_service.py<br/>• 多线程并发控制<br/>• 错误处理与恢复<br/>• 缓存管理]
    
    %% PDF Processing
    PDF[PDF处理<br/>paper_summarizer.py<br/>• PDF下载与验证<br/>• PyMuPDF文本提取<br/>• 智能分块处理<br/>• 缓存策略]
    
    %% AI Processing
    AI[AI摘要生成<br/>• 渐进式摘要<br/>• 多LLM支持<br/>• 智能标签生成<br/>• 提示词工程]
    
    %% LLM Providers
    LLM[LLM提供商<br/>• DeepSeek API<br/>• OpenAI兼容API<br/>• Ollama本地部署<br/>• 自定义端点]
    
    %% Web Interface
    WEB[Web界面<br/>summary_page.py<br/>• Flask应用<br/>• 响应式设计<br/>• 用户管理<br/>• 阅读进度跟踪]
    
    %% Data Storage
    STORAGE[数据存储<br/>• papers/ - PDF缓存<br/>• markdown/ - 文本缓存<br/>• summary/ - 摘要缓存<br/>• user_data/ - 用户数据]
    
    %% User Interface
    UI[用户界面<br/>• 论文列表浏览<br/>• 标签筛选搜索<br/>• 个人阅读管理<br/>• 深色/浅色主题]
    
    %% Flow Connections
    RSS --> SERVICE
    SERVICE --> PDF
    PDF --> AI
    AI --> LLM
    AI --> STORAGE
    SERVICE --> STORAGE
    STORAGE --> WEB
    WEB --> UI
    
    %% Styling
    classDef source fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    classDef process fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef ai fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef storage fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef web fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    classDef ui fill:#f1f8e9,stroke:#689f38,stroke-width:2px
    
    class RSS source
    class SERVICE,PDF process
    class AI,LLM ai
    class STORAGE storage
    class WEB web
    class UI ui
```

## 📁 项目结构

```plaintext
ai-paper-digest/
├── collect_hf_paper_links_from_rss.py    # RSS源链接提取
├── feed_paper_summarizer_service.py      # 服务编排和流程控制
├── paper_summarizer.py                   # PDF下载、解析和AI摘要生成
├── summary_page.py                       # Flask Web应用
├── prompts/                              # AI摘要提示词模板
├── summary/                              # 生成的论文摘要
├── papers/                               # 下载的PDF论文
├── markdown/                             # 提取的Markdown文本
└── ui/                                   # Web界面模板和样式
```

## 🚀 快速开始

### 环境要求
- Python 3.8+
- 现代浏览器（支持ES6+）

### 安装依赖
```bash
# 使用uv包管理器（推荐）
uv sync
```

### 管理员配置
要启用管理员功能（获取最新论文摘要），需要设置环境变量：

```bash
# 设置管理员用户ID（多个用户用逗号分隔）
export ADMIN_USER_IDS="admin,superuser"

# 或者在启动时设置
ADMIN_USER_IDS="admin" python summary_page.py
```

管理员用户可以：
- 在Web界面看到"🔄 获取最新"按钮
- 点击按钮自动运行 `uv run python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed`
- 获取最新的论文摘要并自动刷新页面

### 基础使用

#### 1. 从RSS源获取论文摘要
```bash
python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed \
  --workers 4 \
  --output summaries.md \
  --api-key YOUR_AI_API_KEY
```

#### 2. 启动Web界面
```bash
python summary_page.py
```
访问 http://localhost:22581 即可使用Web界面

#### 3. 重建RSS源
```bash
python feed_paper_summarizer_service.py --rebuild \
  --output_rss_path hugging-face-ai-papers-rss.xml
```

#### 4. 仅生成标签（使用OpenAI兼容API）
```bash
python feed_paper_summarizer_service.py --tags-only \
  --base-url https://api.openai.com/v1 \
  --api-key YOUR_OPENAI_API_KEY
```

#### 5. 仅提取PDF文本（不进行LLM摘要）
```bash
python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed \
  --extract-only \
  --workers 4
```

## 📖 使用指南

### 命令行参数
- `--api-key`：AI模型API密钥（支持DeepSeek、OpenAI等）
- `--workers`：并行处理线程数（默认：CPU核心数）
- `--output`：汇总摘要输出文件
- `--output_rss_path`：RSS文件输出路径
- `--rebuild`：重建RSS文件
- `--local`：处理本地缓存的论文
- `--tags-only`：仅生成标签
- `--debug`：开启调试模式

### Web界面功能

#### 论文浏览
- **首页**：显示最新论文摘要，支持标签筛选
- **标签系统**：顶级分类（LLM、CV、NLP等）+ 细分标签
- **搜索功能**：基于标签的模糊搜索
- **分页浏览**：支持自定义每页显示数量

#### 个人管理
- **用户登录**：设置个人ID，跟踪阅读进度
- **已读列表**：查看已读论文，支持标签筛选
- **阅读统计**：显示总阅读量、今日阅读等数据
- **进度重置**：清空阅读记录重新开始

#### 论文详情
- **完整摘要**：结构化的论文总结内容
- **标签展示**：论文相关的主题标签
- **原始Markdown**：获取摘要的原始格式

## 🔧 技术实现

### 核心模块
- **`collect_hf_paper_links_from_rss.py`**：RSS源链接提取
- **`paper_summarizer.py`**：PDF下载、解析和AI摘要生成
- **`feed_paper_summarizer_service.py`**：服务编排和流程控制
- **`summary_page.py`**：Flask Web应用

### AI摘要流程
1. **PDF下载**：从论文页面解析并下载PDF文件
2. **文本提取**：使用PyMuPDF提取PDF文本内容
3. **智能分块**：按5000字符长度分块，支持重叠
4. **渐进摘要**：使用AI模型逐块生成摘要，最后整合
5. **标签生成**：基于摘要内容生成多级标签

### LLM提供商支持
- **DeepSeek**：默认提供商，支持DeepSeek-v3等模型
- **OpenAI兼容API**：支持任何兼容OpenAI接口的API服务
- **Ollama**：支持本地部署的Ollama服务
- **自定义配置**：可通过`--base-url`参数指定自定义API端点

### 缓存策略
- **PDF缓存**：避免重复下载
- **Markdown缓存**：保存提取的文本
- **摘要缓存**：避免重复生成
- **标签缓存**：快速标签查询

## 🌟 应用场景

### 个人学习
- **快速了解**：几分钟内掌握论文要点
- **知识积累**：系统化学习AI前沿技术
- **研究方向**：发现感兴趣的研究领域

### 团队协作
- **技术分享**：生成易于理解的摘要
- **项目调研**：快速评估相关技术方案
- **知识管理**：建立团队技术知识库

### 学术研究
- **文献综述**：快速浏览大量相关论文
- **研究方向**：了解领域最新进展
- **论文写作**：参考相关工作的创新点

## 📊 性能特点

- **处理速度**：单篇论文摘要生成约2-5分钟
- **并发能力**：支持多线程并行处理
- **缓存效率**：避免重复计算，提升响应速度
- **内存优化**：分块处理大文档，控制内存使用

## 🤝 贡献指南

我们欢迎所有形式的贡献！无论是代码改进、文档完善，还是功能建议，都欢迎参与。

### 贡献方式
1. **Fork项目**：创建你的项目副本
2. **功能开发**：实现新功能或修复问题
3. **测试验证**：确保代码质量和功能正确性
4. **提交PR**：创建Pull Request

### 开发环境
```bash
# 克隆项目
git clone https://github.com/JY0284/ai-paper-digest.git
cd ai-paper-digest

# 安装开发依赖
uv sync

# 运行测试
python -m pytest tests/
```

## 📄 许可证

本项目采用MIT许可证，详见[LICENSE](LICENSE)文件。


## 📞 联系我们

- **GitHub Issues**：[报告问题](https://github.com/JY0284/ai-paper-digest/issues)

---

⭐ **如果这个项目对你有帮助，请给我们一个Star！** ⭐

> **让AI论文阅读不再是负担，而是知识的享受！**
