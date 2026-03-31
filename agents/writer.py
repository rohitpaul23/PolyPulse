import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from state.schema import NewsAgentState, ResearchedStory, WrittenStory

def get_prompt(filename: str) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', filename)
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def _run_llm_with_retries(llms, filled_prompt: str, parse_json: bool = False):
    max_retries_per_model = 3
    
    for model_name, current_llm in llms:
        for attempt in range(max_retries_per_model):
            try:
                print(f"  Attempt {attempt+1} with {model_name}...")
                response = current_llm.invoke(filled_prompt)
                content = response.content.strip()
                
                if parse_json:
                    # Clean JSON blocks
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    
                    try:
                        return json.loads(content, strict=False)
                    except json.JSONDecodeError as e:
                        try:
                            from json_repair import repair_json
                            repaired = repair_json(content)
                            print(f"  [Repaired JSON] Successfully parsed with json_repair for {model_name}.")
                            return json.loads(repaired)
                        except Exception:
                            print(f"  [Warning] json_repair also failed for {model_name}: {e}")
                            time.sleep(2)
                            continue # Try next attempt
                else:
                    return content # Raw text return
                    
            except Exception as e:
                if "429" in str(e):
                    backoff_time = (attempt + 1) * 3
                    print(f"  [Rate Limit] TPM exceeded for {model_name}. Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    print(f"  [Error] {model_name} failed: {e}")
                    break  # Break out to try the next model
    return None

def run_writer(state: NewsAgentState) -> NewsAgentState:
    """
    Takes ResearchedStories and drafts the final blog post, X thread, and LinkedIn snippet
    using three distinct LLM passes for ultimate stability and quality.
    """
    print("--- WRITER AGENT RUNNING (MULTI-PASS) ---")
    
    if not state.researched_stories:
        print("No researched stories to write about.")
        state.current_stage = "writer"
        return state

    # Compile the stories into a massive context block
    stories_context = ""
    for i, s in enumerate(state.researched_stories, 1):
        stories_context += f"\\n[{i}] {s.headline}\\n"
        stories_context += f"Summary: {s.raw_summary}\\n"
        stories_context += f"Background: {s.background_context}\\n"
        stories_context += f"Significance: {s.significance}\\n"
        stories_context += f"Key Players: {', '.join(s.key_players)}\\n"
        stories_context += f"Source URL: {s.url}\\n"
        stories_context += "-" * 40

    roundup_count = len(state.researched_stories) - 1
    timeframe_str = getattr(state, "timeframe", "today")
    topic_str = ", ".join(state.topics) if getattr(state, "topics", None) else "AI News"
    
    replacements = {
        "{total_stories}": str(len(state.researched_stories)),
        "{roundup_count}": str(roundup_count),
        "{stories_context}": stories_context,
        "{topic_string}": topic_str,
        "{timeframe}": timeframe_str
    }

    # Initialize the LLMs
    try:
        llms = [
            ("llama-3.3", ChatGroq(temperature=0.4, model_name="llama-3.3-70b-versatile")),
            ("llama-3.1", ChatGroq(temperature=0.4, model_name="llama-3.1-8b-instant"))
        ]
    except Exception as e:
        error_msg = f"Failed to initialize Groq for writer: {e}"
        print(error_msg)
        state.error_log.append(error_msg)
        return state

    print("Drafting the newsletter and social media assets in 3 sequential passes...")
    
    # PASS 1: BLOG POST (Raw Markdown)
    print("\\n[Pass 1] Generating Blog Post...")
    blog_prompt = get_prompt("writer01_blog.txt")
    for k, v in replacements.items(): blog_prompt = blog_prompt.replace(k, v)
    raw_blog = _run_llm_with_retries(llms, blog_prompt, parse_json=False)
    
    # PASS 2: TWITTER THREAD (JSON Array)
    print("\\n[Pass 2] Generating X/Twitter Thread...")
    twitter_prompt = get_prompt("writer02_twitter.txt")
    for k, v in replacements.items(): twitter_prompt = twitter_prompt.replace(k, v)
    x_thread_full = _run_llm_with_retries(llms, twitter_prompt, parse_json=True)
    if not isinstance(x_thread_full, list):
        print("  [Warning] Twitter output was not a valid list. Defaulting to empty array.")
        x_thread_full = []
        
    # PASS 3: LINKEDIN POST (Raw Text)
    print("\\n[Pass 3] Generating LinkedIn Snippet...")
    linkedin_prompt = get_prompt("writer03_linkedin.txt")
    for k, v in replacements.items(): linkedin_prompt = linkedin_prompt.replace(k, v)
    linkedin_post = _run_llm_with_retries(llms, linkedin_prompt, parse_json=False)


    if not raw_blog:
        error_msg = "Writer Agent completely failed to generate the main blog post."
        print(error_msg)
        state.error_log.append(error_msg)
        return state
        
    print("\\nDraft generation successful!")

    # 1. Source hero image
    # For multillm pass, we no longer rely on LLM for the image term. We intelligently derive it.
    image_search_term = " technology"
    hero_image_md = ""
    fallback_image = "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&q=80"
    top_headline = state.researched_stories[0].headline if state.researched_stories else "AI News"
    
    # Use the primary topic or the first key player
    if state.topics and len(state.topics) > 0:
        image_search_term = state.topics[0]
    elif state.researched_stories and state.researched_stories[0].key_players:
        image_search_term = state.researched_stories[0].key_players[0] + " tech"
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_output_dir = os.path.join(project_root, "output")

    from tools.gen_image import generate_cover_image
    hf_image_path = generate_cover_image(
        headline=top_headline,
        image_theme=image_search_term,
        output_dir=image_output_dir
    )
    if hf_image_path:
        hero_image_md = f"![{image_search_term}]({hf_image_path})\\n\\n"
    else:
        try:
            from duckduckgo_search import DDGS
            results = DDGS().images(keywords=image_search_term, max_results=1)
            if results and len(results) > 0:
                print(f"  [Image] Found image via DuckDuckGo.")
                hero_image_md = f"![{image_search_term}]({results[0].get('image')})\\n\\n"
            else:
                hero_image_md = f"![{image_search_term}]({fallback_image})\\n\\n"
        except Exception as e:
            print(f"  [Warning] DDG image search failed: {e}. Using Unsplash fallback.")
            hero_image_md = f"![{image_search_term}]({fallback_image})\\n\\n"

    # Set outputs (prepending the hero image to the blog)
    # Re-normalize escaped newlines just in case
    raw_blog = raw_blog.replace("\\\\n", "\\n")
    
    lines = raw_blog.split('\\n')
    title_idx = next((i for i, l in enumerate(lines) if l.startswith('# ')), -1)
    if title_idx >= 0:
        lines.insert(title_idx + 1, "\\n" + hero_image_md)
        state.full_blog_post = "\\n".join(lines)
    else:
        state.full_blog_post = hero_image_md + raw_blog

    state.x_thread_full = x_thread_full or []
    state.linkedin_post = linkedin_post or ""
    
    # Fulfill written_stories schema
    written_stories = []
    for s in state.researched_stories:
        written_stories.append(WrittenStory(
            **s.model_dump(),
            mini_article="Aggregated into full_blog_post instead.",
            x_thread=["Aggregated into x_thread_full instead."],
            linkedin_snippet="Aggregated into linkedin_post instead."
        ))
    state.written_stories = written_stories
    state.current_stage = "writer"
    
    return state


if __name__ == "__main__":
    load_dotenv()
    
    test_input_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'researcher_output.json')
    test_output_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'writer_blog_output.md')
    test_state_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'writer_state_output.json')
    
    initial_state = NewsAgentState()
    
    if os.path.exists(test_input_path):
        with open(test_input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            initial_state.researched_stories = [ResearchedStory(**story) for story in data]
            print(f"Loaded {len(initial_state.researched_stories)} researched stories from mock data.")
    else:
        print(f"Error: Could not find mock data at {test_input_path}.")
        sys.exit(1)

    final_state = run_writer(initial_state)

    if final_state.full_blog_post:
        with open(test_output_path, 'w', encoding='utf-8') as f:
            f.write(final_state.full_blog_post)
            f.write("\\n\\n---\\n\\n")
            f.write("### LinkedIn Sneak Peek\\n")
            f.write(final_state.linkedin_post)
            f.write("\\n\\n---\\n\\n")
            f.write("### Twitter/X Thread\\n")
            for i, tweet in enumerate(final_state.x_thread_full, 1):
                f.write(f"\\n**Tweet {i}:**\\n{tweet}\\n")
                
        with open(test_state_path, 'w', encoding='utf-8') as f:
            json.dump(final_state.model_dump(), f, indent=4)
            
        print(f"\\n[SUCCESS]")
        print(f"Saved readable Markdown draft to {test_output_path}")
        print(f"Saved raw state JSON to {test_state_path}")
    else:
        print("\\n[FAILED] Writer agent completely failed to generate data.")
