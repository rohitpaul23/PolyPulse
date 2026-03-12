import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from state.schema import NewsAgentState, ResearchedStory, WrittenStory

def get_writer_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'writer.txt')
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def run_writer(state: NewsAgentState) -> NewsAgentState:
    """
    Takes ResearchedStories and drafts the final blog post, X thread, and LinkedIn snippet.
    """
    print("--- WRITER AGENT RUNNING ---")
    
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

    prompt_template = get_writer_prompt()
    roundup_count = len(state.researched_stories) - 1  # all except the #1 spotlight story
    filled_prompt = (
        prompt_template.replace("{total_stories}", str(len(state.researched_stories)))
                       .replace("{roundup_count}", str(roundup_count))
                       .replace("{stories_context}", stories_context)
    )

    # Initialize the LLMs
    try:
        # Primary: llama-3.3-70b-versatile
        llm_primary = ChatGroq(temperature=0.4, model_name="llama-3.3-70b-versatile")
        # Fallback: llama-3.1-8b-instant (extremely high quota limit)
        llm_fallback = ChatGroq(temperature=0.4, model_name="llama-3.1-8b-instant")
        llms = [("llama-3.3", llm_primary), ("llama-3.1", llm_fallback)]
    except Exception as e:
        error_msg = f"Failed to initialize Groq for writer: {e}"
        print(error_msg)
        state.error_log.append(error_msg)
        return state

    print("Drafting the newsletter and social media assets...")
    
    max_retries_per_model = 3
    success = False
    writer_json = {}
    
    for model_name, current_llm in llms:
        if success:
            break
            
        for attempt in range(max_retries_per_model):
            try:
                print(f"  Attempt {attempt+1} with {model_name}...")
                response = current_llm.invoke(filled_prompt)
                content = response.content.strip()
                
                # Clean JSON blocks
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                    
                writer_json = json.loads(content.strip(), strict=False)
                success = True
                break  # Success, exit the retry loop for this model
                
            except json.JSONDecodeError as e:
                # Try json_repair as secondary parser (fixes unescaped apostrophes in Markdown)
                try:
                    from json_repair import repair_json
                    repaired = repair_json(content.strip())
                    writer_json = json.loads(repaired)
                    success = True
                    print(f"  [Repaired JSON] Successfully parsed with json_repair for {model_name}.")
                    break
                except Exception:
                    print(f"  [Warning] json_repair also failed for {model_name}: {e}")
                    time.sleep(2)
            except Exception as e:
                if "429" in str(e):
                    backoff_time = (attempt + 1) * 3
                    print(f"  [Rate Limit] TPM exceeded for {model_name}. Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    print(f"  [Error] {model_name} failed: {e}")
                    break  # Break out to try the next model

    if not success or not writer_json:
        error_msg = "Writer Agent failed to generate content from all LLM attempts."
        print(error_msg)
        state.error_log.append(error_msg)
        return state
        
    print("Draft generation successful!")

    # Populate final state outputs
    
    # 1. Source hero image — 3-tier priority:
    #    (a) HuggingFace FLUX.1-schnell AI generation (requires HF_TOKEN in .env)
    #    (b) DuckDuckGo image search using LLM's keyword
    #    (c) Static Unsplash AI photo fallback
    image_search_term = writer_json.get("image_search_term", "artificial intelligence technology")
    hero_image_md = ""
    fallback_image = "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&q=80"
    top_headline = state.researched_stories[0].headline if state.researched_stories else "AI News"
    
    # Determine the output dir relative to the project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_output_dir = os.path.join(project_root, "output")

    # (a) Try HuggingFace FLUX.1-schnell AI generation
    from tools.gen_image import generate_cover_image
    hf_image_path = generate_cover_image(
        headline=top_headline,
        image_theme=image_search_term,
        output_dir=image_output_dir
    )
    if hf_image_path:
        # Use the absolute path for Markdown embedding (works in VSCode preview and local readers)
        hero_image_md = f"![{image_search_term}]({hf_image_path})\n\n"
    else:
        # (b) DDG image search
        try:
            from duckduckgo_search import DDGS
            results = DDGS().images(keywords=image_search_term, max_results=1)
            if results and len(results) > 0:
                print(f"  [Image] Found image via DuckDuckGo.")
                hero_image_md = f"![{image_search_term}]({results[0].get('image')})\n\n"
            else:
                hero_image_md = f"![{image_search_term}]({fallback_image})\n\n"
        except Exception as e:
            print(f"  [Warning] DDG image search failed: {e}. Using Unsplash fallback.")
            hero_image_md = f"![{image_search_term}]({fallback_image})\n\n"

    # Set outputs (prepending the hero image to the blog)
    raw_blog = writer_json.get("full_blog_post", "")
    # Normalize escaped newlines from the JSON LLM output to real newlines
    raw_blog = raw_blog.replace("\\n", "\n")
    
    # Find the title line and insert the hero image directly below it
    lines = raw_blog.split('\n')
    title_idx = next((i for i, l in enumerate(lines) if l.startswith('# ')), -1)
    if title_idx >= 0:
        lines.insert(title_idx + 1, "\n" + hero_image_md)
        state.full_blog_post = "\n".join(lines)
    else:
        state.full_blog_post = hero_image_md + raw_blog

    state.x_thread_full = writer_json.get("x_thread", [])
    state.linkedin_post = writer_json.get("linkedin_snippet", "")
    
    # We map back into written_stories just to fulfill the schema pipeline tracking
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
    
    # Load mock data from Researcher
    if os.path.exists(test_input_path):
        with open(test_input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            initial_state.researched_stories = [ResearchedStory(**story) for story in data]
            print(f"Loaded {len(initial_state.researched_stories)} researched stories from mock data.")
    else:
        print(f"Error: Could not find mock data at {test_input_path}.")
        sys.exit(1)

    # Run the writer agent
    final_state = run_writer(initial_state)

    if final_state.full_blog_post:
        # Save Markdown Blog for humans to read
        with open(test_output_path, 'w', encoding='utf-8') as f:
            f.write(final_state.full_blog_post)
            f.write("\\n\\n---\\n\\n")
            f.write("### LinkedIn Sneak Peek\\n")
            f.write(final_state.linkedin_post)
            f.write("\\n\\n---\\n\\n")
            f.write("### Twitter/X Thread\\n")
            for i, tweet in enumerate(final_state.x_thread_full, 1):
                f.write(f"\\n**Tweet {i}:**\\n{tweet}\\n")
                
        # Save JSON State for Publisher
        with open(test_state_path, 'w', encoding='utf-8') as f:
            # We serialize the full final state
            json.dump(final_state.model_dump(), f, indent=4)
            
        print(f"\\n[SUCCESS]")
        print(f"Saved readable Markdown draft to {test_output_path}")
        print(f"Saved raw state JSON to {test_state_path}")
    else:
        print("\\n[FAILED] Writer agent completely failed to generate data.")
