const storyData = {
    meta: {
        title: {
            en: "AI Paper Digest: The Evolution",
            zh: "AI Paper Digest: 进化之路"
        },
        subtitle: {
            en: "From a simple script to an intelligent research companion.",
            zh: "从简单的脚本到智能化的科研伴侣。"
        },
        footer: {
            en: "A journey of 157 days, 132 commits, and one goal: Better reading.",
            zh: "157天的旅程，132次提交，只为一个目标：更好的阅读体验。"
        }
    },
    stats: {
        title: {
            en: "Development Insights",
            zh: "开发洞察"
        },
        heatmap_title: {
            en: "Commit Activity",
            zh: "提交活跃度"
        },
        time_title: {
            en: "Coding Hours",
            zh: "编码时段"
        },
        metrics: {
            commits: {
                label: { en: "Total Commits", zh: "总提交数" },
                value: 133
            },
            days: {
                label: { en: "Active Days", zh: "活跃天数" },
                value: 34
            },
            hours: {
                label: { en: "Development Span", zh: "开发跨度" },
                value: "157 Days"
            }
        },
        // Raw data generated from python script
        heatmap: {"2025-12-21": 5, "2025-12-20": 3, "2025-12-19": 1, "2025-12-17": 3, "2025-12-16": 2, "2025-12-15": 2, "2025-12-14": 3, "2025-12-13": 3, "2025-12-12": 2, "2025-12-01": 2, "2025-11-30": 12, "2025-11-27": 1, "2025-11-24": 3, "2025-11-10": 2, "2025-11-09": 6, "2025-10-11": 2, "2025-10-10": 7, "2025-09-21": 1, "2025-09-09": 1, "2025-09-08": 7, "2025-08-31": 21, "2025-09-07": 1, "2025-08-30": 13, "2025-08-26": 1, "2025-08-25": 6, "2025-08-24": 6, "2025-08-10": 5, "2025-08-09": 4, "2025-08-08": 1, "2025-08-07": 1, "2025-08-05": 1, "2025-08-04": 2, "2025-07-18": 1, "2025-07-17": 2},
        time_dist: {"morning": 28, "afternoon": 38, "evening": 47, "night": 20},
        time_labels: {
            morning: { en: "Morning (6-12)", zh: "上午 (6-12)" },
            afternoon: { en: "Afternoon (12-18)", zh: "下午 (12-18)" },
            evening: { en: "Evening (18-24)", zh: "晚上 (18-24)" },
            night: { en: "Night (0-6)", zh: "深夜 (0-6)" }
        }
    },
    chapters: [
        {
            date: "July 17, 2025",
            title: {
                en: "The Spark",
                zh: "星星之火"
            },
            description: {
                en: "It started with a personal pain point: too many papers, too little time. A simple Python script was born to download PDFs and use AI to summarize them. It was raw, command-line only, but it worked.",
                zh: "一切始于一个痛点：论文太多，时间太少。一个简单的 Python 脚本诞生了，用于下载 PDF 并利用 AI 生成摘要。虽然简陋，只有命令行，但它能用。"
            },
            tags: ["Idea", "CLI", "Python"],
            icon: "💡"
        },
        {
            date: "August 4, 2025",
            title: {
                en: "From Script to Screen",
                zh: "从脚本到屏幕"
            },
            description: {
                en: "Reading JSON output in a terminal wasn't enough. The project evolved into a Flask web app. Suddenly, abstract concepts became a visual interface. This was the moment it transformed from a 'tool' to a 'product'.",
                zh: "在终端阅读 JSON 输出远远不够。项目演变成了 Flask Web 应用。突然间，抽象的概念变成了可视化的界面。这是它从“工具”转变为“产品”的时刻。"
            },
            tags: ["Flask", "Web App", "UI"],
            icon: "🖥️"
        },
        {
            date: "August 9, 2025",
            title: {
                en: "Designing for Humans",
                zh: "为人类设计"
            },
            description: {
                en: "Research often happens late at night. We introduced Dark Mode and a Tagging System. It wasn't just about processing text anymore; it was about the reading experience and organizing knowledge.",
                zh: "科研往往发生在深夜。我们引入了深色模式和标签系统。这不再仅仅是处理文本，而是关乎阅读体验和知识组织。"
            },
            tags: ["UX", "Dark Mode", "Tags"],
            icon: "🎨"
        },
        {
            date: "August 24-25, 2025",
            title: {
                en: "Freedom of Choice",
                zh: "选择的自由"
            },
            description: {
                en: "Why rely on just one AI? We unlocked support for local LLMs (Ollama) and OpenAI-compatible APIs. Whether you wanted privacy, low cost, or raw power, the choice became yours.",
                zh: "为什么要依赖单一的 AI？我们解锁了对本地 LLM (Ollama) 和 OpenAI 兼容 API 的支持。无论你想要隐私、低成本还是高性能，选择权都在你手中。"
            },
            tags: ["Ollama", "Multi-LLM", "Local"],
            icon: "🔓"
        },
        {
            date: "August 31, 2025",
            title: {
                en: "The Architecture Shift",
                zh: "架构重塑"
            },
            description: {
                en: "As complexity grew, the code struggled. In a 48-hour sprint (29 commits!), the monolithic app was dismantled and rebuilt into modular services. It was the growing pain needed for future scale.",
                zh: "随着复杂度增加，代码变得难以维护。在48小时的冲刺（29次提交！）中，单体应用被拆解并重建为模块化服务。这是未来扩展所必需的阵痛。"
            },
            tags: ["Refactoring", "Modular", "Architecture"],
            icon: "🏗️"
        },
        {
            date: "September 8, 2025",
            title: {
                en: "Finding the Needle",
                zh: "大海捞针"
            },
            description: {
                en: "With hundreds of papers accumulated, browsing wasn't enough. We added a robust Search engine and Mobile Navigation. The library was now searchable and accessible from your pocket.",
                zh: "随着数百篇论文的积累，仅靠浏览已不够。我们添加了强大的搜索引擎和移动端导航。现在的图书馆不仅可搜索，还能装进口袋。"
            },
            tags: ["Search", "Mobile", "Accessibility"],
            icon: "🔍"
        },
        {
            date: "October 11, 2025",
            title: {
                en: "Workflow Integration",
                zh: "工作流集成"
            },
            description: {
                en: "Reading isn't just consuming; it's planning. We added 'Todo Lists' and 'Favorites'. The digest became a workspace where researchers could manage their reading pipeline.",
                zh: "阅读不仅仅是消费，更是规划。我们添加了“待读清单”和“收藏夹”。摘要系统变成了一个工作区，研究人员可以在此管理他们的阅读流程。"
            },
            tags: ["Todo", "Favorites", "Workflow"],
            icon: "✅"
        },
        {
            date: "November 24-30, 2025",
            title: {
                en: "The AI Gets Personal",
                zh: "AI 变得懂你"
            },
            description: {
                en: "The system stopped being passive. With a new Recommendation Engine and 'Deep Read' features, it started understanding what users liked and offering deeper, section-level insights.",
                zh: "系统不再被动。借助新的推荐引擎和“深度阅读”功能，它开始理解用户的喜好，并提供更深入的、章节级的洞察。"
            },
            tags: ["Recommendations", "Personalization", "Deep Read"],
            icon: "🧠"
        },
        {
            date: "December 16, 2025",
            title: {
                en: "Pulse of the Community",
                zh: "社区脉搏"
            },
            description: {
                en: "What is the world reading? The 'Trending' feature was introduced to track hot topics over 7 and 30 days, connecting individual reading with broader community trends.",
                zh: "世界在读什么？引入了“趋势”功能，追踪过去7天和30天的热点话题，将个人阅读与更广泛的社区趋势联系起来。"
            },
            tags: ["Trending", "Analytics", "Community"],
            icon: "📈"
        },
        {
            date: "December 21, 2025",
            title: {
                en: "The Platform Today",
                zh: "今日平台"
            },
            description: {
                en: "Today, it's a robust platform with Quota Management, Async Processing, and a polished UI. It's no longer just a script; it's a dedicated assistant helping researchers stay ahead.",
                zh: "今天，它是一个拥有配额管理、异步处理和精美 UI 的强大平台。它不再只是一个脚本，而是帮助研究人员保持领先的专属助手。"
            },
            tags: ["Current State", "Quota", "Async"],
            icon: "🚀"
        }
    ]
};
