# hugging-face-paper-reader-rss

`hugging-face-paper-reader-rss` 是一个用于快速生成学术论文摘要的轻量级服务。它通过从指定的 RSS 提要中提取论文链接，利用 DeepSeek AI 技术下载并总结每篇论文。此项目旨在帮助用户快速获取学术论文的摘要，提升阅读效率。

## 主要功能

1. **从 RSS 提要获取论文链接**：从指定的 RSS 提要中提取论文链接，支持如 HuggingFace、ArXiv 等常见源。
2. **生成论文摘要**：使用 DeepSeek API 对下载的 PDF 论文进行文本提取和摘要生成。
3. **并行处理**：支持多线程并行处理，提升批量论文摘要生成的效率。
4. **汇总摘要**：将所有生成的摘要合并为一个 Markdown 文件，方便用户查看。
5. **更新 RSS 提要**：生成的论文摘要将被添加到指定的 RSS 提要中，支持保留最新的条目。

## 项目结构

```plaintext
.
├── collect_hf_paper_links_from_rss.py        # 用于从 RSS 获取论文链接
├── feed_paper_summarizer_service.py          # 服务主脚本，负责整体流程
├── hugging-face-ai-papers-rss.xml            # 生成的 RSS 文件
├── markdown                                  # 存放从 PDF 提取的 Markdown 格式论文
├── output.md                                 # 汇总的论文摘要 Markdown 文件
├── paper_summarizer.py                       # 论文摘要生成模块
├── papers                                    # 存放下载的 PDF 论文
├── prompts                                   # 存放摘要生成的模板
├── summary                                   # 存放生成的论文摘要
├── tests                                     # 存放测试代码
├── README.md                                 # 项目的说明文档
└── uv.lock                                   # 依赖锁文件
```

## 安装与使用

### 环境要求

* Python 3.x
* 必须安装项目依赖的 Python 包，如 `tqdm`、`markdown`、`feedgen` 等。

### 安装依赖

在项目根目录下执行以下命令，安装所有依赖：

```bash
uv sync
```

### 使用说明

1. **从 RSS 提要获取论文并生成摘要**

   使用以下命令启动服务，指定 RSS 提要链接，工作线程数，并设置输出文件路径：

   ```bash
   python feed_paper_summarizer_service.py <RSS_URL> --workers <num_workers> --output <output_file.md>
   ```

   例如，从 HuggingFace 获取论文摘要：

   ```bash
   python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed --workers 4 --output summaries.md
   ```

2. **可选参数**

   * `--api-key`：DeepSeek API 密钥（可选）。
   * `--proxy`：PDF 下载代理 URL（如有需要）。
   * `--workers`：并行处理的工作线程数（默认使用 CPU 核心数）。
   * `--output`：输出的汇总文件路径（默认为 `output.md`）。
   * `--output_rss_path`：生成的 RSS 文件路径（默认为 `hugging-face-ai-papers-rss.xml`）。
   * `--rebuild`：是否重新生成 RSS 文件，使用现有的摘要文件重建。
   * `--debug`：开启调试模式，输出详细日志。

3. **生成和更新 RSS 提要**

   可以在生成摘要时同时更新或重建 RSS 提要，命令如下：

   ```bash
   python feed_paper_summarizer_service.py <RSS_URL> --output_rss_path <path_to_rss_file> --rebuild
   ```

## 工作原理

1. **获取论文链接**：服务会从指定的 RSS 提要 URL 获取所有论文链接，并进行去重。
2. **并行摘要生成**：为每个论文链接下载 PDF 文件，并通过 DeepSeek 提取文本并生成摘要。
3. **汇总摘要**：将所有论文的摘要合并为一个 Markdown 文件，便于查看。
4. **更新 RSS 提要**：将生成的摘要和论文链接更新到 RSS 提要文件中，最多保留最新的 30 条记录。

## 示例

假设你使用以下命令从 RSS 提要获取论文，并生成摘要文件和更新 RSS 提要：

```bash
python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed --workers 4 --output summaries.md --output_rss_path hugging-face-ai-papers-rss.xml
```

该命令会：

1. 从 HuggingFace RSS 提要中获取论文链接。
2. 使用 4 个工作线程并行处理论文。
3. 将生成的摘要保存到 `summaries.md` 文件中。
4. 更新或重建 `hugging-face-ai-papers-rss.xml` 文件，包含最新的摘要条目。

## 贡献

欢迎贡献代码、报告问题或提出功能请求！请按照以下步骤参与：

1. Fork 本仓库。
2. 提交您的代码变更。
3. 创建 Pull Request。