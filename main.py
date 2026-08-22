from langgraph.types import Command
from src.graph import build_graph

def run_pipeline():
    graph, store = build_graph()
    config = {"configurable": {"thread_id": "TICKET_RUN_001"}}

    initial_input = {
        "ticket_id": "TICKET_RUN_001",
        "customer_id": "CUST_999",
        "raw_email_thread": ["Hello, I received a broken display monitor. Order ID is ORD-777 and it cost $650."],
        "retry_count": 0
    }

    print("=== TEST 1: Initial Processing ===")
    for event in graph.stream(initial_input, config=config):
        print(event)

    print("\n=== STORE RECORDS FOR CUST_999 ===")
    print(store.search(("customers", "CUST_999")))

if __name__ == "__main__":
    run_pipeline()