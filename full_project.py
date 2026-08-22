import json
import operator
from typing import Annotated, Literal, TypedDict,List,Optional
from pydantic import BaseModel

from langgraph.store.base import BaseStore
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore




class TicketState(TypedDict):
    ticket_id: str               # Thread ID (UUID)
    customer_id: str             # Global customer ID
    raw_email_thread: Annotated[List[str], operator.add]  # Multi-turn customer email text
    issue_summary: str           # Output from isolated transcript sub-agent
    order_id: str                # Extracted order number
    claim_amount: float          # Refund requested
    missing_fields: List[str]    # Missing details needed from customer
    retry_count: int             # Information gathering loop counter
    requires_approval: bool      # Calculated risk flag
    approval_status: str         # "PENDING", "APPROVED", "REJECTED"
    final_resolution: str        # System action taken
    extracted_data: str

from pydantic import BaseModel, Field
from typing import Optional

class ExtractedEmailData(BaseModel):
    issue_summary: str = Field(
        description="Brief summary of the customer's issue"
    )
    order_id: Optional[str] = Field(
        default=None, 
        description="Order identifier mentioned, such as ORD-777"
    )
    claim_amount: Optional[float] = Field(
        default=None, 
        description=(
            "Extracted monetary refund or claim amount converted into a raw float (e.g., 650.0). "
            "Handle all natural language formats: "
            "1. With symbols: '$650', '650$', '£650' -> 650.0 "
            "2. Without symbols: '650', '650.00' -> 650.0 "
            "3. Written in words: 'six hundred fifty', 'two hundred dollars' -> 650.0 or 200.0 "
            "4. With currency strings: '650 USD', '650 bucks' -> 650.0. "
            "Return null if no price or amount is mentioned."
        )
    )

llm = ChatOllama(model="llama3.2", temperature=0)


def retrieve_info_node(state: TicketState) -> dict:
    email_thread = "\n\n".join(state["raw_email_thread"])
    prompt = (
        "You are an AI assistant tasked with extracting structured information from a customer support email thread.\n"
        "The email thread is as follows:\n\n"
        f"{email_thread}\n\n"
        "Please extract the following details:\n"
        "- Issue summary\n"
        "- Order ID (e.g., ORD-123)\n"
        "- Claim amount as a plain number (e.g., extract '$650' as 650.0)\n\n"
        "Return your response in JSON format with keys: 'issue_summary', 'order_id', 'claim_amount'.\n"
        "If any field is missing, set its value to null."
    )

    structured_llm = llm.with_structured_output(ExtractedEmailData)
    extracted: ExtractedEmailData = structured_llm.invoke(prompt)
    
    return {
        "extracted_data": {
            "issue_summary": extracted.issue_summary,
            "order_id": extracted.order_id,
            "claim_amount": extracted.claim_amount
        }
    }
'''
def check_missing_list(state: TicketState)-> dict:
    missing_list=state.get("missing_fields")
    extracted_data=state.get("extracted_data",{})
    if missing_list is None:
        missing_list=[]
    else:

def supervisor_node(state: TicketState) -> dict:
    extracted_data = state.get("extracted_data", {})
    issue_summary = extracted_data.get("issue_summary", "")
    order_id = extracted_data.get("order_id")
    claim_amount = extracted_data.get("claim_amount")

    # Determine if any critical fields are missing
    missing_fields = []
    if not issue_summary:
        missing_fields.append("issue_summary")
    if not order_id:
        missing_fields.append("order_id")
    if claim_amount is None:
        missing_fields.append("claim_amount")

    # Determine if approval is required based on claim amount
    requires_approval = False
    approval_status = "PENDING"
   

    return {
        "issue_summary": issue_summary,
        "order_id": order_id,
        "claim_amount": claim_amount,
        "missing_fields": missing_fields,
        "requires_approval": requires_approval,
        "approval_status": approval_status,
        "retry_count":1
    }

'''
def supervisor_node(state: TicketState, store: BaseStore) -> dict:
    extracted_data = state.get("extracted_data", {})
    issue_summary = state.get("issue_summary") or extracted_data.get("issue_summary", "")
    order_id = state.get("order_id") or extracted_data.get("order_id")
    claim_amount = state.get("claim_amount") if state.get("claim_amount") is not None else extracted_data.get("claim_amount")
    customer_id = state.get("customer_id")

    # 1. Identify missing fields
    missing_fields = []
    if not issue_summary: missing_fields.append("issue_summary")
    if not order_id: missing_fields.append("order_id")
    if claim_amount is None: missing_fields.append("claim_amount")

    # 2. Check for Duplicate Claim on same Order ID
    existing_order = store.get(namespace=("orders", order_id), key="refund_record") if order_id else None
    if existing_order:
        return {
            "issue_summary": issue_summary,
            "order_id": order_id,
            "claim_amount": claim_amount,
            "missing_fields": missing_fields,
            "requires_approval": False,
            "approval_status": "REJECTED_DUPLICATE",
            "retry_count": state.get("retry_count", 1)
        }

    # 3. Check Cumulative Risk (> $500 threshold)
    past_claims = store.search(("customers", customer_id)) if customer_id else []
    # Check both "claim_amount" and "amount" keys for backwards compatibility
    total_past_refunds = sum(
        c.value.get("claim_amount", c.value.get("amount", 0.0)) 
        for c in past_claims
    )
    
    current_claim = claim_amount or 0.0
    high_risk_customer = (total_past_refunds + current_claim) > 500.0

    return {
        "issue_summary": issue_summary,
        "order_id": order_id,
        "claim_amount": claim_amount,
        "missing_fields": missing_fields,
        "requires_approval": high_risk_customer,
        "approval_status": "PENDING" if high_risk_customer else "APPROVED",
        "retry_count": state.get("retry_count", 1)
    }

def missing_data_node(state: TicketState, store: BaseStore) -> dict:
    missing = list(state.get("missing_fields", []))
    count = state.get("retry_count", 1)

    # Retain current state variables
    issue_summary = state.get("issue_summary", "")
    order_id = state.get("order_id")
    claim_amount = state.get("claim_amount")
    customer_id = state.get("customer_id")

    # Base case: exit loop early if no fields are missing
    if not missing:
        return {"missing_fields": [], "retry_count": 0}

    # PASS 1: Re-examine email thread using LLM structured output
    if count == 1:
        email_text = "\n".join(state.get("raw_email_thread", []))
        prompt = (
            f"Re-examine this customer email thread specifically to extract these missing fields: {', '.join(missing)}.\n\n"
            f"Email Thread:\n{email_text}"
        )
        try:
            structured_llm = llm.with_structured_output(ExtractedEmailData)
            extracted: ExtractedEmailData = structured_llm.invoke(prompt)

            if extracted.issue_summary:
                issue_summary = extracted.issue_summary
            if extracted.order_id:
                order_id = extracted.order_id
            if extracted.claim_amount is not None:
                claim_amount = extracted.claim_amount
        except Exception:
            pass  # Maintain existing state if parsing fails

    # PASS 2: Cross-reference global Store memory for missing IDs
    elif count == 2:
        # Case A: Missing customer_id -> Reverse Lookup using order_id
        if not customer_id and order_id:
            order_record = store.get(namespace=("orders", order_id), key="refund_record")
            if order_record:
                customer_id = order_record.value.get("customer_id")

        # Case B: Missing order_id -> Forward Lookup using customer_id
        if customer_id and not order_id:
            past_records = store.search(("customers", customer_id))
            if past_records:
                latest_record = past_records[-1].value
                order_id = latest_record.get("order_id")

    # PASS 3+: Exhausted automated recovery attempts
    else:
        pass

    # Always re-evaluate remaining missing fields (guarantees safe variable scoping)
    updated_missing = []
    if not issue_summary:
        updated_missing.append("issue_summary")
    if not order_id:
        updated_missing.append("order_id")
    if claim_amount is None:
        updated_missing.append("claim_amount")
    if not customer_id:
        updated_missing.append("customer_id")

    return {
        "issue_summary": issue_summary,
        "order_id": order_id,
        "claim_amount": claim_amount,
        "customer_id": customer_id,
        "missing_fields": updated_missing,
        "retry_count": count + 1
    }

from langgraph.types import interrupt

# Interrupt 1: Customer Info Request Node
def manager_approve(state: TicketState):
    # Execution freezes HERE until customer responds
    manager_response = interrupt({
        "status": "WAITING_FOR_CUSTOMER",
        "missing_fields": state["missing_fields"]
    })
    
    # Execution resumes HERE when customer submits data
    return {"approval_status": manager_response.get("approval_status", "APPROVED")}

def request_customer_info_node(state: TicketState):
    # Execution freezes HERE until customer responds
    customer_payload = interrupt({
        "status": "WAITING_FOR_CUSTOMER",
        "missing_fields": state["missing_fields"]
    })
    
    # Execution resumes HERE when customer submits data
    return {
        "raw_email_thread": [customer_payload.get("message", "")],
        "missing_fields": []
    }

def check_missing_validation(state: TicketState) -> str:
    miss=state.get("missing_fields")
    if  state.get("retry_count")==0:
        return "check_aproval"
    elif state.get("retry_count")>3:
        return "back_to_customer"
    else:
        return "check_missing"

def check_approval_validation(state: TicketState) -> str:
    approval_status = state.get("approval_status")
    if approval_status in ["APPROVED", "REJECTED", "REJECTED_DUPLICATE"]:
        return "end"
    elif approval_status == "PENDING":
        return "back_to_manager"
    return "end"

def check_approval(state: TicketState, store: BaseStore) -> dict:
    approval_status = state.get("approval_status", "PENDING")
    requires_approval = state.get("requires_approval", False)
    customer_id = state.get("customer_id")
    order_id = state.get("order_id")
    claim_amount = state.get("claim_amount", 0.0)

    # Do not process or save duplicates
    if approval_status == "REJECTED_DUPLICATE":
        return {"approval_status": "REJECTED_DUPLICATE", "requires_approval": False}

    # Pause for manager approval if cumulative threshold exceeded
    if requires_approval:
        manager_response = interrupt({
            "status": "WAITING_FOR_MANAGER",
            "claim_amount": claim_amount,
            "reason": "Cumulative limit exceeded (> $500)"
        })
        approval_status = manager_response.get("approval_status", "APPROVED")

    # Save to Store if approved
    if approval_status == "APPROVED":
        record = {
            "customer_id": customer_id,
            "order_id": order_id,
            "claim_amount": claim_amount,
            "status": "APPROVED"
        }
        if order_id:
            store.put(namespace=("orders", order_id), key="refund_record", value=record)
        if customer_id:
            store.put(namespace=("customers", customer_id), key=order_id, value=record)

    return {
        "requires_approval": requires_approval,
        "approval_status": approval_status
    }

workflow = StateGraph(TicketState)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("retrieve", retrieve_info_node)
workflow.add_node("check_missing", missing_data_node)
workflow.add_node("check_aproval", check_approval)
workflow.add_node("back_to_customer", request_customer_info_node)
workflow.add_node("back_to_manager", manager_approve)

workflow.add_edge(START, "retrieve")
workflow.add_edge("retrieve", "supervisor")
workflow.add_edge("supervisor", "check_missing")
workflow.add_conditional_edges("check_missing", check_missing_validation, {"check_missing": "check_missing",
                                                             "check_aproval": "check_aproval",
                                                             "back_to_customer":"back_to_customer"})

workflow.add_conditional_edges("check_aproval", check_approval_validation, 
                               {"end": END, "back_to_manager": "back_to_manager"})
# Add these missing edges to your workflow
workflow.add_edge("back_to_customer", "retrieve")
workflow.add_edge("back_to_manager", END)


checkpointer = MemorySaver()
store = InMemoryStore()

# Both are passed during graph compilation
graph = workflow.compile(checkpointer=checkpointer, store=store)

if __name__ == "__main__":
    from langgraph.types import Command

    # 1. Set thread config (required by MemorySaver)
    config = {"configurable": {"thread_id": "TICKET_RUN_001"}}

    # 2. Define initial input state (triggers high-risk cumulative claim check > $500)
    initial_input = {
        "ticket_id": "TICKET_RUN_001",
        "customer_id": "CUST_999",
        "raw_email_thread": [
            "Hello, I received a broken display monitor in my shipment. Order ID is ORD-777 and it cost $650."
        ],
        "retry_count": 0
    }

    print("\n=== STEP 1: Initial Graph Stream Execution ===")
    for event in graph.stream(initial_input, config=config):
        print("Event:", event)

    # 3. Inspect state to verify graph paused at an interrupt()
    current_state = graph.get_state(config)
    print("\n=== GRAPH PAUSED AT INTERRUPT ===")
    print("Next Node Waiting to Execute:", current_state.next)

    # 4. Resume execution if graph is paused (e.g., waiting for manager approval or customer reply)
    if current_state.next:
        print("\n=== STEP 2: Resuming Graph Execution with Command ===")
        
        # Payload matching your interrupt return expected format
        resume_payload = Command(resume={"approval_status": "APPROVED", "message": "ORD-777 verified."})
        
        for event in graph.stream(resume_payload, config=config):
            print("Event:", event)

    # 5. Output final resolved thread state
    print("\n=== FINAL TICKET STATE ===")
    final_state = graph.get_state(config)
    print("Values:", final_state.values)

    # 6. Verify Cross-Thread Persistence in Store
    print("\n=== STORE INSPECTION (Cross-Thread Record) ===")
    saved_records = store.search(("customers", "CUST_999"))
    print("Store records found for CUST_999:", [r.value for r in saved_records])

    # --- TEST CASE 2: Duplicate Order ID (ORD-777) ---
    print("\n=== TEST 2: Duplicate Claim Check ===")
    config_2 = {"configurable": {"thread_id": "TICKET_RUN_002"}}
    ticket_2_input = {
        "ticket_id": "TICKET_RUN_002",
        "customer_id": "CUST_999",
        "raw_email_thread": ["Hello, submitting a new request for broken item in ORD-777 for $650."],
        "retry_count": 0
    }

    for event in graph.stream(ticket_2_input, config=config_2):
        print("Event:", event)


    # --- TEST CASE 3: New Order ID but Cumulative Total > $500 ---
    print("\n=== TEST 3: Cumulative Risk Threshold Check ===")
    config_3 = {"configurable": {"thread_id": "TICKET_RUN_003"}}
    ticket_3_input = {
        "ticket_id": "TICKET_RUN_003",
        "customer_id": "CUST_999",
        "raw_email_thread": ["Another package ORD-888 arrived damaged, claiming $200."],
        "retry_count": 0
    }

    for event in graph.stream(ticket_3_input, config=config_3):
        print("Event:", event)

    