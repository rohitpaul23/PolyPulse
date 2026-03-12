import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from state.schema import NewsAgentState, VerifiedStory
from tools.search import search_news

def get_fact_checker_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'fact_checker.txt')
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def run_fact_checker(state: NewsAgentState) -> NewsAgentState:
    """
    Verifies each raw story using web search and Groq LLM.
    Keeps only VERIFIED and UNVERIFIED stories, drops DISPUTED ones.
    """
    print("--- FACT-CHECKER AGENT RUNNING ---")
    current_date = datetime.now().isoformat()
    
    if not state.raw_stories:
        print("No raw stories to verify.")
        state.current_stage = "fact_checker"
        return state

    verified_stories = []
    
    # Initialize the LLM (Using Groq since Google API is hitting 404 access restrictions)
    try:
        llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")
    except Exception as e:
        error_msg = f"Failed to initialize Groq for fact-checking: {e}"
        print(error_msg)
        state.error_log.append(error_msg)
        return state

    prompt_template = get_fact_checker_prompt()

    for i, story in enumerate(state.raw_stories, 1):
        print(f"[{i}/{len(state.raw_stories)}] Verifying: {story.headline}...")
        
        # 1. Search independently to verify the story
        search_query = f"{story.headline} news"
        try:
            results = search_news(search_query, max_results=3)
            search_results_text = "\\n\\n".join([
                f"Title/Content: {r.get('title', '')} {r.get('content', '')}\\nURL: {r.get('url', '')}" 
                for r in results
            ])
        except Exception as e:
            print(f"  Search failed for verification: {e}")
            search_results_text = "No independent search results available due to an error."
            
        # 2. Ask Groq to verify
        # We manually replace the prompt format since we aren't using Langchain PromptTemplate
        filled_prompt = (
            prompt_template.replace("{headline}", story.headline)
                           .replace("{url}", story.url)
                           .replace("{raw_summary}", story.raw_summary)
                           .replace("{search_results}", search_results_text)
                           .replace("{current_date}", current_date)
        )
        
        try:
            response = llm.invoke(filled_prompt)
            content = response.content.strip()
            
            # Clean JSON blocks
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
                
            verification_data = json.loads(content)
            
            # Safety check on confidence score threshold overrides
            v_status = verification_data.get("verification_status", "pending").lower()
            conf_score = float(verification_data.get("confidence_score", 0.0))
            
            if conf_score >= 0.7:
                v_status = "verified"
            elif 0.4 <= conf_score < 0.7:
                v_status = "unverified"
            else:
                v_status = "disputed"
            
            # 3. Create VerifiedStory object
            v_story = VerifiedStory(
                headline=story.headline,
                url=story.url,
                source=story.source,
                raw_summary=story.raw_summary,
                scraped_at=story.scraped_at,
                verification_status=v_status,
                confidence_score=conf_score,
                supporting_sources=verification_data.get("supporting_sources", []),
                verification_notes=verification_data.get("verification_notes", "")
            )
            
            # 4. Filter logic: Drop disputed stories
            print(f"  -> Status: {v_status.upper()} (Score: {conf_score})")
            if v_status in ["verified", "unverified"]:
                verified_stories.append(v_story)
            else:
                print(f"  -> DROPPED: Story disputed.")
                
        except Exception as e:
            print(f"  -> LLM Error verifying story: {e}")
            state.error_log.append(f"FactChecker LLM error on story '{story.headline}': {e}")
            
    # 5. Sort by confidence score (highest first) and truncate to target
    verified_stories.sort(key=lambda s: s.confidence_score, reverse=True)
    
    target = state.target_stories
    if len(verified_stories) > target:
        print(f"\\nTruncating from {len(verified_stories)} down to target {target} stories.")
        verified_stories = verified_stories[:target]
        
    print(f"\\nVerified {len(verified_stories)} stories for the final output.")
    state.verified_stories = verified_stories
    state.current_stage = "fact_checker"
    
    return state

if __name__ == "__main__":
    from dotenv import load_dotenv
    from state.schema import RawStory
    load_dotenv()
    
    print("Testing Fact-Checker Agent locally")
    test_file_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'scraper_output.json')
    
    initial_state = NewsAgentState()
    try:
        initial_state.target_stories = int(os.getenv("TARGET_STORIES", "10"))
    except ValueError:
        pass
        
    # Load mock data if it exists
    if os.path.exists(test_file_path):
        with open(test_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            initial_state.raw_stories = [RawStory(**s) for s in data]
        print(f"Loaded {len(initial_state.raw_stories)} stories from mock data.")
    else:
        print("No mock data found! Run the scraper first with: python -m agents.scraper")
        sys.exit(1)
        
    new_state = run_fact_checker(initial_state)
    
    # Save the output for the next agent (Researcher)
    out_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'fact_checker_output.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump([s.model_dump() for s in new_state.verified_stories], f, indent=2)
        
    print(f"Saved verified stories to {out_path} for next pipeline steps.")
