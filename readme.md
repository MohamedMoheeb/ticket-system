# Enterprise Claims Agent: Stateful Multi-Agent Support Architecture

A production-ready, fault-tolerant support ticket automation engine built with **LangGraph**, **Ollama (Llama 3.2)**, and **Pydantic**. Features cross-thread memory, Human-in-the-Loop (HITL) execution pauses, and cumulative risk-governance checks.

## Architecture Flow

```mermaid
graph TD
    A[Start: Customer Email] --> B[retrieve_node: Structured Output Extraction]
    B --> C[supervisor_node: Duplicate & Risk Evaluator]
    C --> D[check_missing: Multi-Pass Recovery]
    
    D -- Missing Data & Retries < 3 --> D
    D -- Missing Data & Retries >= 3 --> E[back_to_customer: Interrupt Pause]
    E -- Resumed with Command --> B
    
    D -- Data Complete --> F[check_approval: Risk & Threshold Check]
    F -- Cumulative Risk > $500 --> G[manager_approve: HITL Interrupt Pause]
    F -- Auto-Approved / Rejected --> H[Write to BaseStore & END]
    G -- Manager Decision --> H


```	
	
##Key Technical FeaturesStateful Human-in-the-Loop (HITL): 
* Uses native LangGraph interrupt() and Command(resume=...) to freeze execution and wait for asynchronous customer or manager input without thread loss.
* Cross-Session BaseStore Memory: Maintains transactional state across distinct execution threads (thread_id) to automatically block duplicate order claims (ORD-XXX) and enforce cumulative monetary risk limits ($500 cap per customer).
* Defensive Extraction & Multi-Pass Recovery: Utilizes structured Pydantic schema validation for local model (Llama 3.2) output parsing, backed by a 2-pass fallback recovery mechanism (LLM retry $\rightarrow$ BaseStore key-value lookup).
	
Quickstart

Bash
# Setup Virtual Environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Dependencies
pip install langgraph langchain-ollama pydantic

# Ensure Ollama is running Llama 3.2 locally
ollama run llama3.2

# Execute Test Suite
python main.py