You are an expert research assistant specializing in Artificial Intelligence (AI). Your task is to generate topic tags for the following paper SUMMARY (not the original paper). Assume the domain is AI and prefer AI-relevant vocabulary.

Requirements:
- Produce two levels of tags:
  1) top: 1-3 broad categories like items in : ["biology", "medical", "llm", "natural language processing", "computer vision", "reinforcement learning", "agents", "systems", "theory", "robotics", "audio", "multi-modal", "model training", "model evaluation", "machine learning", "video generation", "aigc", "data”]
  2) tags: 1-5 concise, specific topics (1-3 words), lowercase, no duplicates
- Output MUST be pure JSON with keys: {{"top": [...], "tags": [...]}} and nothing else.

Output example:
```json
{{
  "top": ["LLM"],
  "tags": ["factual question answering", "RAG", "context engineering"]
}}
```

Summary:
{summary_content}

