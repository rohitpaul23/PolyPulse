import sys
import os
import json
import asyncio
import threading
import queue
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

from state.schema import NewsAgentState
from graph import app as langgraph_app

load_dotenv()

app = FastAPI(title="PolyPulse AI News Agent UI")

# Ensure output directory exists
project_root = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(project_root, "output"), exist_ok=True)

class PrintCapture:
    """A wrapper to capture stdout to a queue while also printing it."""
    def __init__(self, original_stdout, q):
        self.original_stdout = original_stdout
        self.queue = q
        
    def write(self, text):
        if text.strip():
            self.queue.put_nowait(text.strip())
        self.original_stdout.write(text)
        
    def flush(self):
        self.original_stdout.flush()

@app.post("/api/run")
async def run_agent(request: Request):
    """
    Kicks off the LangGraph swarm. Returns an SSE stream of the logs,
    and finishes with a 'done' event containing the final state.
    """
    data = await request.json()
    target_stories = int(data.get("target_stories", 10))
    
    raw_topics = data.get("topics", "AI News")
    # Split out CSV topics
    topics = [t.strip() for t in raw_topics.split(",") if t.strip()]
    if not topics:
        topics = ["AI News"]
        
    post_x = data.get("post_x", False)
    post_linkedin = data.get("post_linkedin", False)
    post_blog = data.get("post_blog", False)
    timeframe = data.get("timeframe", "today")

    initial_state = NewsAgentState(
        target_stories=target_stories,
        topics=topics,
        timeframe=timeframe,
        post_to_x=post_x,
        post_to_linkedin=post_linkedin,
        post_to_blog=post_blog
    )

    async def event_generator():
        q = queue.Queue()
        orig_stdout = sys.stdout
        
        def run_graph():
            capture = PrintCapture(orig_stdout, q)
            sys.stdout = capture
            try:
                # We use .invoke which runs the entire graph to completion.
                # All agent print() calls go through our PrintCapture.
                result = langgraph_app.invoke(initial_state)
                # Pydantic v2 .model_dump()
                state_dict = result.model_dump() if hasattr(result, "model_dump") else result
                q.put({"type": "done", "state": state_dict})
            except Exception as e:
                q.put({"type": "error", "error": str(e)})
            finally:
                sys.stdout = orig_stdout
        
        # Run graph in background thread so async generator can yield live
        thread = threading.Thread(target=run_graph)
        thread.start()
        
        while thread.is_alive() or not q.empty():
            try:
                item = q.get_nowait()
                if isinstance(item, dict):
                    if item["type"] == "done":
                        yield {"event": "done", "data": json.dumps(jsonable_encoder(item["state"]))}
                        break
                    elif item["type"] == "error":
                        yield {"event": "error", "data": json.dumps({"error": item["error"]})}
                        break
                else:
                    yield {"event": "log", "data": json.dumps({"message": item})}
            except queue.Empty:
                await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())


# Serve frontend files
os.makedirs(os.path.join(project_root, "web"), exist_ok=True)
app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Web UI on http://127.0.0.1:8000")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
