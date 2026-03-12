import os
import sys
from dotenv import load_dotenv
from state.schema import NewsAgentState
from graph import app

def main():
    """
    Main entry point for the AI News Multi-Agent System.
    Orchestrates the full pipeline using LangGraph.
    """
    # 1. Load environment variables
    load_dotenv()

    # 2. Configure project root for exports
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(project_root, "output"), exist_ok=True)
    os.makedirs(os.path.join(project_root, "test"), exist_ok=True)

    print("==========================================")
    print("   AI NEWS MULTI-AGENT PIPELINE STARTING  ")
    print("==========================================")

    # 3. Initialize state
    initial_state = NewsAgentState()
    try:
        initial_state.target_stories = int(os.getenv("TARGET_STORIES", "10"))
    except ValueError:
        initial_state.target_stories = 10

    # 4. Invoke the LangGraph workflow
    # Each agent node will print its own status updates to the console.
    try:
        result = app.invoke(initial_state)
        
        print("\n==========================================")
        print("         PIPELINE RUN COMPLETE            ")
        print("==========================================")
        
        if result.get("error_log"):
            print("\nWarnings/Errors encountered during run:")
            for err in result["error_log"]:
                print(f" - {err}")
                
        print(f"\nSummary:")
        print(f" - Stories found     : {len(result.get('raw_stories', []))}")
        print(f" - Stories verified  : {len(result.get('verified_stories', []))}")
        print(f" - Stories researched: {len(result.get('researched_stories', []))}")
        print(f" - Blog post drafted : {'Yes' if result.get('full_blog_post') else 'No'}")
        print(f" - X thread posted   : {'Yes' if result.get('published_to_x') else 'No (Composition only)'}")
        
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Pipeline execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
