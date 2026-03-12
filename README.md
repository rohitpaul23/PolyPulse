# PolyPulse: Multi-Agent AI News Pipeline 🤖📰

A fully automated, multi-agent AI system that discovers, verifies, researches, and publishes daily AI news. Built with **LangGraph**, **Groq (Llama 3)**, and **Playwright**.

## 🚀 Overview

This system automates the lifecycle of an AI news briefing. It uses a swarm of specialized agents to ensure high-quality, verified content is delivered daily to social media and local storage.

### Key Features
- **Smart Discovery**: Scrapes the web for the most significant AI breakthroughs.
- **Deep Verification**: Cross-references stories to maintain a high "Confidence Score".
- **Parallel Research**: Deep-dives into context and significance using concurrent LLM calls.
- **Multi-Platform Publishing**: 
  - **Newsletter**: Professional Markdown format with AI-generated cover images (FLUX.1).
  - **X (Twitter)**: Clean, emoji-rich threads with robust browser automation fallback.
  - **LinkedIn**: Direct posting via official API.

## 🏗️ Architecture

The pipeline is orchestrated as a linear graph using **LangGraph**:

1.  **Scraper**: Discovers top AI stories via Tavily/DuckDuckGo.
2.  **Fact-Checker**: Assigns confidence scores and filters out noise.
3.  **Researcher**: Parallel synthesis of background and key players.
4.  **Writer**: Drafts the newsletter and social media threads.
5.  **Publisher**: Distributes to folders and social platforms.

---

## 🛠️ Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/ai-news-agent.git
cd ai-news-agent
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
playwright install
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```bash
# LLM & Search
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key

# X / Twitter (Optional for API post)
TWITTER_API_KEY=...
TWITTER_API_SECRET=...

# X / Twitter Browser Automation (Fallback)
TWITTER_EMAIL=...
TWITTER_PASSWORD=...

# LinkedIn
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_PERSON_URN=...

# AI Images (HuggingFace)
HF_TOKEN=your_hf_token
```

---

## 🏃 Usage

Run the entire pipeline with a single command:

```bash
python main.py
```

Outputs will be saved in the `output/` directory as Markdown (`.md`), JSON, and PNG cover images.

## 📄 License
MIT License.

---
*Created with ❤️ by the AI News Team.*
