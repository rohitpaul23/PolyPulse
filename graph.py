from langgraph.graph import StateGraph, START, END
from state.schema import NewsAgentState
from agents.scraper import run_scraper
from agents.fact_checker import run_fact_checker
from agents.researcher import run_researcher
from agents.writer import run_writer
from agents.publisher import run_publisher

def create_graph():
    # 1. Initialize State Graph with our shared schema
    workflow = StateGraph(NewsAgentState)

    # 2. Add individual agent nodes
    workflow.add_node("scraper", run_scraper)
    workflow.add_node("fact_checker", run_fact_checker)
    workflow.add_node("researcher", run_researcher)
    workflow.add_node("writer", run_writer)
    workflow.add_node("publisher", run_publisher)

    # 3. Define the linear pipeline
    # Scraper -> Fact-Checker -> Researcher -> Writer -> Publisher
    workflow.add_edge(START, "scraper")
    workflow.add_edge("scraper", "fact_checker")
    workflow.add_edge("fact_checker", "researcher")
    workflow.add_edge("researcher", "writer")
    workflow.add_edge("writer", "publisher")
    workflow.add_edge("publisher", END)

    # 4. Compile the graph
    return workflow.compile()

# Export compiled app
app = create_graph()
