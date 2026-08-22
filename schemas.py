import operator
from typing import Annotated, List, Optional, TypedDict
from pydantic import BaseModel, Field

class ExtractedEmailData(BaseModel):
    issue_summary: str = Field(description="Brief summary of the customer's issue")
    order_id: Optional[str] = Field(default=None, description="Order identifier like ORD-777")
    claim_amount: Optional[float] = Field(
        default=None, 
        description=(
            "Extracted monetary refund or claim amount converted into a raw float (e.g., 650.0). "
            "Handle symbols ($650), plain numbers (650), words (six hundred fifty), or currency strings (650 USD)."
        )
    )

class TicketState(TypedDict):
    ticket_id: str
    customer_id: Optional[str]
    raw_email_thread: Annotated[List[str], operator.add]
    issue_summary: str
    order_id: Optional[str]
    claim_amount: Optional[float]
    missing_fields: List[str]
    retry_count: int
    requires_approval: bool
    approval_status: str
    extracted_data: dict