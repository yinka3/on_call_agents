import json
import logging
from typing import Optional
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from flask import app
from pydantic import ValidationError
import redis
from documentation import search_documentation
from gemini import GeminiEmbeddingFunction, gemini
import models
from utils import build_initial_message
from slack import search_slack_history, slack_client

load_dotenv()
app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)


def store_prometheus_alerts(incident_id: str, payload: models.PrometheusWebhookPayload) -> None:
    """Saves incoming Prometheus alerts to Redis."""
    alert_fingerprints = []
    for alert in payload.alerts:
        alert_fingerprints.append(alert.fingerprint)
        redis_client.set(
            f"prometheus:alert:{alert.fingerprint}",
            alert.model_dump_json(indent=2),
            ex=7200
        )

    if alert_fingerprints:
        redis_client.sadd(f"payload:{incident_id}", *alert_fingerprints)
        redis_client.expire(f"payload:{incident_id}", 7200)

def find_related_information(query: str) -> dict:
    """Searches documentation and Slack for context related to a query."""
    doc_results = search_documentation(query_text=query)
    slack_results = search_slack_history(query_text=query)
    return {
        "documentation": doc_results,
        "slack_history": slack_results
    }

def post_slack_update(channel: str, thread_ts: str, text: str):
    """Posts a message to a specific Slack thread."""
    try:
        slack_client.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=thread_ts
        )
    except Exception as e:
        logging.error(f"Failed to post update to Slack: {e}")

def run_incident_workflow(incident_id: str, payload: models.PrometheusWebhookPayload, thread_ts: str):
    """
    Orchestrates the entire incident response workflow.
    """

    store_prometheus_alerts(incident_id, payload)

    summary_data = summarize_alerts(incident_id)
    if not summary_data or not summary_data.get("llm_response"):
        logging.error("Failed to generate AI summary. Aborting workflow.")
        post_slack_update(
            channel="#test-on-call",
            thread_ts=thread_ts,
            text="⚠️ I was unable to generate an AI summary for this alert."
        )
        return

    ai_summary = summary_data["llm_response"]
    post_slack_update(
        channel="#test-on-call",
        thread_ts=thread_ts,
        text=f"🔍 *AI Summary:* {ai_summary}"
    )

    # 3. Find and post related information
    related_info = find_related_information(ai_summary)
    doc_results = related_info["documentation"]
    slack_results = related_info["slack_history"]

    if doc_results:
        post_slack_update(
            channel="#test-on-call",
            thread_ts=thread_ts,
            text=f"📚 *Related Documentation:*\n{doc_results}"
        )

    if slack_results:
        post_slack_update(
            channel="#test-on-call",
            thread_ts=thread_ts,
            text=f"💬 *Related Conversations:*\n{slack_results}"
        )

def summary_on_alerts(payload_id: Optional[str]):
    
    alerts_fingerprints = redis_client.smembers(f"payload:{payload_id}")
    if not alerts_fingerprints:
        return

    alert_keys = [f"prometheus:alert:{fp}" for fp in alerts_fingerprints]
    alerts = redis_client.mget(alert_keys)

    llm_context = "The following related alerts are firing:\n\n"
    alert_cnt = 0

    for alert in alerts:
        if alert is None:
            continue

        alert_data = json.loads(alert)
        alert_cnt += 1

        summary = alert_data.get("annotations", {}).get("summary", "N/A")
        description = alert_data.get("annotations", {}).get("description", "N/A")
        alertname = alert_data.get("labels", {}).get("alertname", "N/A")
        server = alert_data.get("labels", {}).get("instance", "N/A")
        
        llm_context += f"--- Alert {alert_cnt} ---\n"
        llm_context += f"Name: {alertname}\n"
        llm_context += f"Summary: {summary}\n"
        llm_context += f"Description: {description}\n\n"
        llm_context += f"Instance: {server}\n\n"

    llm_response = summarize_alerts(llm_context)
    get_embeddings = GeminiEmbeddingFunction(llm_response)
    return {"llm_context": llm_context, "llm_response": llm_response, "embeddings": get_embeddings}


def summarize_alerts(context):
    if not context:
        raise ValueError("There should be some context available")
    
    model_response = gemini.models.generate_content(model='gemini-2.0-flash-001', contents=context)
    return model_response.text

@app.post('/webhook/prome')
async def promethues_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload_json = await request.json()
        payload = models.PrometheusWebhookPayload.model_validate(payload_json)

    except ValidationError as e:
        logging.error(f"Pydantic Validation Error: {e.errors()}")
        logging.error(f"--- FAILING PAYLOAD ---")
        logging.error(json.dumps(payload_json, indent=2))
        logging.error(f"-----------------------")
        raise HTTPException(
            status_code=422,
            detail={"error": "Pydantic validation failed", "details": e.errors()}
        )
    initial_message = build_initial_message(payload)    
    try:
        response = slack_client.chat_postMessage(
            channel="#test-on-call", 
            blocks=initial_message
        )
        thread_ts = response["message"]["ts"]

        background_tasks.add_task(run_incident_workflow, str(uuid4()), payload, thread_ts)

    except Exception as e:
        logging.error(f"Failed to post to Slack or start background task: {e}")
        return {"status": "received_but_failed_downstream", "code": 200}
    
    return {"status": "received", "code": 200}

