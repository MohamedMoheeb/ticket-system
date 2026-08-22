from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from langchain_ollama import ChatOllama
from src.schemas import TicketState, ExtractedEmailData

llm = ChatOllama(model="llama3.2", temperature=0)

def retrieve_node(state: TicketState) -> dict:
    email_text = "\n".join(state.get("raw_email_thread", []))
    prompt = f"Extract ticket details from this customer email:\n\n{email_text}"
    
    try:
        structured_llm = llm.with_structured_output(ExtractedEmailData)
        extracted: ExtractedEmailData = structured_llm.invoke(prompt)
        data = {
            "issue_summary": extracted.issue_summary or "",
            "order_id": extracted.order_id,
            "claim_amount": extracted.claim_amount
        }
    except Exception:
        data = {"issue_summary": "", "order_id": None, "claim_amount": None}

    return {"extracted_data": data}

def supervisor_node(state: TicketState, store: BaseStore) -> dict:
    extracted = state.get("extracted_data", {})
    issue_summary = state.get("issue_summary") or extracted.get("issue_summary", "")
    order_id = state.get("order_id") or extracted.get("order_id")
    claim_amount = state.get("claim_amount") if state.get("claim_amount") is not None else extracted.get("claim_amount")
    customer_id = state.get("customer_id")

    missing = []
    if not issue_summary: missing.append("issue_summary")
    if not order_id: missing.append("order_id")
    if claim_amount is None: missing.append("claim_amount")

    # Duplicate Order Check across sessions
    if order_id and store.get(namespace=("orders", order_id), key="refund_record"):
        return {
            "issue_summary": issue_summary, "order_id": order_id, "claim_amount": claim_amount,
            "missing_fields": missing, "requires_approval": False,
            "approval_status": "REJECTED_DUPLICATE", "retry_count": state.get("retry_count", 0)
        }

    # Cumulative Risk Check across sessions (> $500)
    past_claims = store.search(("customers", customer_id)) if customer_id else []
    total_past = sum(c.value.get("claim_amount", 0.0) for c in past_claims)
    high_risk = (total_past + (claim_amount or 0.0)) > 500.0

    return {
        "issue_summary": issue_summary, "order_id": order_id, "claim_amount": claim_amount,
        "missing_fields": missing, "requires_approval": high_risk,
        "approval_status": "PENDING" if high_risk else "APPROVED",
        "retry_count": state.get("retry_count", 0)
    }

def missing_data_node(state: TicketState, store: BaseStore) -> dict:
    missing = list(state.get("missing_fields", []))
    count = state.get("retry_count", 1)
    
    if not missing:
        return {"missing_fields": [], "retry_count": 0}

    issue_summary, order_id, claim_amount, customer_id = (
        state.get("issue_summary", ""), state.get("order_id"), state.get("claim_amount"), state.get("customer_id")
    )

    if count == 1:
        email_text = "\n".join(state.get("raw_email_thread", []))
        try:
            structured_llm = llm.with_structured_output(ExtractedEmailData)
            extracted = structured_llm.invoke(f"Re-scan for missing fields ({missing}):\n{email_text}")
            issue_summary = extracted.issue_summary or issue_summary
            order_id = extracted.order_id or order_id
            claim_amount = extracted.claim_amount if extracted.claim_amount is not None else claim_amount
        except Exception:
            pass

    elif count == 2:
        if not customer_id and order_id:
            rec = store.get(namespace=("orders", order_id), key="refund_record")
            if rec: customer_id = rec.value.get("customer_id")
        elif customer_id and not order_id:
            recs = store.search(("customers", customer_id))
            if recs: order_id = recs[-1].value.get("order_id")

    updated_missing = []
    if not issue_summary: updated_missing.append("issue_summary")
    if not order_id: updated_missing.append("order_id")
    if claim_amount is None: updated_missing.append("claim_amount")

    return {
        "issue_summary": issue_summary, "order_id": order_id, "claim_amount": claim_amount,
        "customer_id": customer_id, "missing_fields": updated_missing, "retry_count": count + 1
    }

def request_customer_info_node(state: TicketState) -> dict:
    payload = interrupt({"status": "WAITING_FOR_CUSTOMER", "missing_fields": state["missing_fields"]})
    return {"raw_email_thread": [payload.get("message", "")], "missing_fields": []}

def check_approval_node(state: TicketState, store: BaseStore) -> dict:
    approval_status = state.get("approval_status", "PENDING")
    requires_approval = state.get("requires_approval", False)

    if approval_status == "REJECTED_DUPLICATE":
        return {"approval_status": "REJECTED_DUPLICATE"}

    if requires_approval:
        mgr_resp = interrupt({"status": "WAITING_FOR_MANAGER", "claim_amount": state.get("claim_amount")})
        approval_status = mgr_resp.get("approval_status", "REJECTED")

    if approval_status == "APPROVED":
        record = {
            "customer_id": state.get("customer_id"), "order_id": state.get("order_id"),
            "claim_amount": state.get("claim_amount", 0.0), "status": "APPROVED"
        }
        if state.get("order_id"):
            store.put(namespace=("orders", state["order_id"]), key="refund_record", value=record)
        if state.get("customer_id"):
            store.put(namespace=("customers", state["customer_id"]), key=state["order_id"], value=record)

    return {"approval_status": approval_status}