import os
import sys
import json
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from state.schema import NewsAgentState, VerifiedStory, ResearchedStory
from tools.search import search_news

def get_researcher_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'researcher.txt')
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def process_single_story(story: VerifiedStory, prompt_template: str, llms: list) -> ResearchedStory:
    """Worker function to process a single story concurrently."""
    try:
        # 1. Search for deep-dive background info
        search_query = f"{story.headline} history background context company"
        results = search_news(search_query, max_results=3)
        search_results_text = "\\n\\n".join([
            f"Title/Content: {r.get('title', '')} {r.get('content', '')}\\nURL: {r.get('url', '')}" 
            for r in results
        ])
    except Exception as e:
        print(f"  [Error] Deep-dive search failed for '{story.headline[:30]}...': {e}")
        search_results_text = "No additional research available."

    # 2. Ask Groq to synthesize the background research
    filled_prompt = (
        prompt_template.replace("{headline}", story.headline)
                       .replace("{raw_summary}", story.raw_summary)
                       .replace("{source}", story.source)
                       .replace("{verification_notes}", story.verification_notes or "None")
                       .replace("{search_results}", search_results_text)
    )

    researched_data = {
        "background_context": "Failed to analyze background.",
        "key_players": [],
        "related_stories": [],
        "significance": "Unknown significance."
    }

    import time
    import time
    import re
    
    max_retries_per_model = 3
    success = False
    
    for model_name, current_llm in llms:
        if success:
            break
            
        for attempt in range(max_retries_per_model):
            try:
                response = current_llm.invoke(filled_prompt)
                content = response.content.strip()
                
                # Remove think blocks for DeepSeek reasoning models
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

                # Clean JSON blocks
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                    
                research_json = json.loads(content.strip())
                
                # Merge with defaults to ensure schema matches
                researched_data.update(research_json)
                success = True
                break  # Success, exit the retry loop for this model
                
            except json.JSONDecodeError:
                print(f"  [Warning] Failed to parse JSON for '{story.headline[:30]}...' using {model_name}")
                break  # Not a rate limit, normal loop exit (try next model)
            except Exception as e:
                if attempt < max_retries_per_model - 1 and "429" in str(e):
                    backoff_time = (attempt + 1) * 3
                    print(f"  [Rate Limit] TPM exceeded for {model_name} on '{story.headline[:30]}...'. Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    print(f"  [Error] {model_name} failed to research story '{story.headline[:30]}...': {e}")
                    break  # Break out to try the next model
        
    print(f"  -> Finished researching: {story.headline[:40]}...")

    # 3. Create ResearchedStory
    return ResearchedStory(
        **story.model_dump(),
        background_context=researched_data.get("background_context", ""),
        key_players=researched_data.get("key_players", []),
        related_stories=researched_data.get("related_stories", []),
        significance=researched_data.get("significance", "")
    )


def run_researcher(state: NewsAgentState) -> NewsAgentState:
    """
    Takes VerifiedStories and performs deep-dive research to add context.
    Executes searches and LLM calls in parallel to speed up the pipeline.
    """
    print("--- RESEARCHER AGENT RUNNING ---")
    
    if not state.verified_stories:
        print("No verified stories to research.")
        state.current_stage = "researcher"
        return state

    prompt_template = get_researcher_prompt()
    
    # Initialize the LLMs
    try:
        # Primary: llama-3.3-70b-versatile
        llm_primary = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")
        # Fallback: llama-3.1-8b-instant (extremely high quota limit)
        llm_fallback = ChatGroq(temperature=0, model_name="llama-3.1-8b-instant")
        llms = [("llama-3.3", llm_primary), ("llama-3.1", llm_fallback)]
    except Exception as e:
        error_msg = f"Failed to initialize Groq for researching: {e}"
        print(error_msg)
        state.error_log.append(error_msg)
        return state

    print(f"Starting parallel research for {len(state.verified_stories)} stories...")
    researched_stories_unsorted = []

    # Using ThreadPoolExecutor for concurrent I/O (API calls to Tavily and Groq)
    # 5 workers manages concurrent API limits while providing a large speedup
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all tasks
        future_to_story = {
            executor.submit(process_single_story, story, prompt_template, llms): story 
            for story in state.verified_stories
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_story):
            try:
                result_story = future.result()
                researched_stories_unsorted.append(result_story)
            except Exception as e:
                story = future_to_story[future]
                error_msg = f"Parallel processing failed for story '{story.headline}': {e}"
                print(f"  [Error] {error_msg}")
                state.error_log.append(error_msg)

    print(f"\\nResearched {len(researched_stories_unsorted)} out of {len(state.verified_stories)} stories.")
    
    # Sort them back to original confidence score order since concurrency scrambles completion times
    # O(N^2) search is fine for N=10 stories
    researched_stories = []
    for vs in state.verified_stories:
        for rs in researched_stories_unsorted:
            if rs.url == vs.url:
                researched_stories.append(rs)
                break
    
    state.researched_stories = researched_stories
    state.current_stage = "researcher"
    
    return state


if __name__ == "__main__":
    load_dotenv()
    
    test_input_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'fact_checker_output.json')
    test_output_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'researcher_output.json')
    
    initial_state = NewsAgentState()
    
    # Load mock data from Fact-Checker if it exists
    if os.path.exists(test_input_path):
        with open(test_input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Reconstruct VerifiedStory objects
            initial_state.verified_stories = [VerifiedStory(**story) for story in data]
            print(f"Loaded {len(initial_state.verified_stories)} verified stories from mock data.")
    else:
        print(f"Error: Could not find mock data at {test_input_path}. Run fact_checker.py first.")
        sys.exit(1)

    # Run the researcher agent
    final_state = run_researcher(initial_state)

    # Save output for the Writer agent to use later
    with open(test_output_path, 'w', encoding='utf-8') as f:
        # Convert Pydantic models to dicts for JSON serialization
        json_data = [story.model_dump() for story in final_state.researched_stories]
        json.dump(json_data, f, indent=4)
        
    print(f"Saved researched stories to {test_output_path} for next pipeline steps.")
