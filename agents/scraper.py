import os
import sys
import json
from datetime import datetime

# Adjust the path so we can import modules properly when running as __main__
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from state.schema import NewsAgentState, RawStory
from tools.search import search_news

def get_scraper_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'scraper.txt')
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def run_scraper(state: NewsAgentState) -> NewsAgentState:
    """
    Finds the top 10 AI news stories and updates the state.
    """
    print("--- SCRAPER AGENT RUNNING ---")
    current_date = datetime.now().isoformat()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    '''
    queries = [
        f"AI news today {today_str}",
        f"artificial intelligence research breakthrough {today_str}"
    ]
    '''
    timeframe_str = getattr(state, "timeframe", "today")
    queries = [f"{topic} {timeframe_str} {today_str}" for topic in state.topics]
    
    all_results = []
    seen_urls = set()
    
    print("Searching for news...")
    
    # Calculate how many stories to extract in total
    target_stories = state.target_stories
    try:
        story_buffer = int(os.getenv("STORY_BUFFER", "5"))
    except ValueError:
        story_buffer = 5
        
    total_to_extract = target_stories + story_buffer
    
    for query in queries:
        try:
            # We fetch up to 6 results per query now to hit a larger pool,
            # giving the LLM enough raw data to return `total_to_extract` distinct stories
            # without hitting the Groq 12000 TPM limit
            results = search_news(query, max_results=6)
            for r in results:
                url = r.get('url')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
        except Exception as e:
            print(f"Error executing search query '{query}': {e}")
            state.error_log.append(f"Scraper search error: {e}")

    # Prepare context for LLM
    search_results_text = "\\n\\n".join([
        f"Title/Content: {r.get('title', '')} {r.get('content', '')}\\nURL: {r.get('url', '')}" 
        for r in all_results
    ])

    prompt_template = get_scraper_prompt()
    prompt = PromptTemplate.from_template(prompt_template)
    filled_prompt = prompt.format(
        total_to_extract=total_to_extract,
        search_results=search_results_text,
        current_date=current_date
    )

    print(f"Analyzing {len(all_results)} valid search results with LLM to extract top {total_to_extract} stories...")
    
    import time
    llms = [
        ("llama-3.3", ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")),
        ("llama-3.1", ChatGroq(temperature=0, model_name="llama-3.1-8b-instant"))
    ]
    
    max_retries = 3
    success = False
    
    for model_name, current_llm in llms:
        if success:
            break
            
        for attempt in range(max_retries):
            try:
                response = current_llm.invoke(filled_prompt)
                content = response.content.strip()
                
                # Clean JSON blocks
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                    
                content = content.strip()

                stories_json = json.loads(content)
                
                raw_stories = []
                for s in stories_json:
                    if 'scraped_at' not in s:
                        s['scraped_at'] = current_date
                    raw_stories.append(RawStory(**s))
                    
                print(f"Found {len(raw_stories)} raw stories.")
                state.raw_stories = raw_stories
                state.current_stage = "scraper"
                success = True
                break
                
            except json.JSONDecodeError as e:
                print(f"  [Warning] Failed to parse JSON using {model_name}: {e}")
                break  # Normal loop exit -> try next model
            except Exception as e:
                if attempt < max_retries - 1 and "429" in str(e):
                    backoff = (attempt + 1) * 3
                    print(f"  [Rate Limit] TPM exceeded for {model_name}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    print(f"  [Error] {model_name} failed: {e}")
                    break
                    
    if not success:
        error_msg = "All models and retries failed to extract stories."
        print(f"Scraper agent LLM error: {error_msg}")
        state.error_log.append(f"Scraper LLM error: {error_msg}")

    return state

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    print("Testing Scraper Agent")
    initial_state = NewsAgentState()
    new_state = run_scraper(initial_state)
    print("\\nScraped stories:")
    for i, story in enumerate(new_state.raw_stories, 1):
        print(f"{i}. {story.headline} ({story.url})")
        
    # Save output for offline testing of downstream agents
    test_out_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'scraper_output.json')
    with open(test_out_path, 'w', encoding='utf-8') as f:
        # Pydantic v2 dump
        json.dump([s.model_dump() for s in new_state.raw_stories], f, indent=2)
    print(f"\\nSaved raw stories to {test_out_path} for mock testing.")
