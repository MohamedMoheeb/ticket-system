from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from src.schemas import TicketState
from src.nodes import (
    retrieve_node, supervisor_node, missing_data_node, 
    request_customer_info_node, check_approval_node
)

def check_missing_validation(state: TicketState) -> str:
    if state.get("missing_fields"):
        if state.get("retry_count", 0) >= 3:
            return "back_to_customer"
        return "check_missing"
    return "check_approval"

def check_approval_validation(state: TicketState) -> str:
    if state.get("approval_status") == "PENDING" and state.get("requires_approval"):
        return "check_approval"
    return END

def build_graph():
    builder = StateGraph(TicketState)

    builder.add_node("retrieve", retrieve_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("check_missing", missing_data_node)
    builder.add_node("back_to_customer", request_customer_info_node)
    builder.add_node("check_approval", check_approval_node)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "supervisor")
    builder.add_edge("supervisor", "check_missing")

    builder.add_conditional_edges(
        "check_missing",
        check_missing_validation,
        {"check_missing": "check_missing", "back_to_customer": "back_to_customer", "check_approval": "check_approval"}
    )
    builder.add_edge("back_to_customer", "retrieve")
    builder.add_conditional_edges("check_approval", check_approval_validation, {"check_approval": "check_approval", END: END})

    checkpointer = MemorySaver()
    shared_store = InMemoryStore()
    
    return builder.compile(checkpointer=checkpointer, store=shared_store), shared_store