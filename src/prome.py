import json
import logging
import os
from typing import Optional
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from flask import app
from pydantic import ValidationError
import redis
from embedding import GeminiEmbeddingFunction
import models
from utils import build_initial_message
from google import genai
from google.genai import types
import chromadb
from slack import search_slack_history, slack_client

load_dotenv()
app = FastAPI()
chromadb_client = chromadb.Client()
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)


def run_incident_workflow(id: str, payload: models.PrometheusWebhookPayload, thread_ts: str):

    alert_fingerprints = []
    for alert in payload.alerts:
        alert_fingerprints.append(alert.fingerprint)
        redis_client.set(f"prometheus:alert:{alert.fingerprint}", alert.model_dump_json(indent=2), ex=7200)
    
    if alert_fingerprints:
        redis_client.sadd(f"payload:{id}", *alert_fingerprints)
        redis_client.expire(f"payload:{id}", 7200)
    redis_client.set(f"incident:{id}:thread_ts", thread_ts)
    summary = summary_on_alerts(id)
    if not summary or not summary.get("llm_response"):
        logging.error("Failed to generate AI summary. Aborting workflow.")
        return

    llm_response = summary["llm_response"]
    slack_client.chat_postMessage(channel="#test-on-call", text=f"AI Summary: {llm_response}", thread_ts=thread_ts)
    slack_results = search_slack_history(query_text=llm_response)
    summary["slack_results"] = slack_results
    slack_client.chat_postMessage(channel="#test-on-call", text=f"Found related conversations:\n{slack_results}", thread_ts=thread_ts)


# gets context, gets llm response and then embeds it and stores it, this should definitely go into a redis db
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

    llm_response = get_hallucinated_context(llm_context)
    get_embeddings = GeminiEmbeddingFunction(llm_response)
    # redis_client.hset(key=f"Payload:{payload_id}", value={"llm_context": llm_context, "llm_response": llm_response, "embeddings": get_embeddings})
    return {"llm_context": llm_context, "llm_response": llm_response, "embeddings": get_embeddings}


def get_hallucinated_context(context):
    if not context:
        raise ValueError("There should be some context available")
    
    model_response = gemini.models.generate_content(model='gemini-2.0-flash-001', contents=context)
    return model_response.text

@app.post('/webhook/prome')
async def promethues_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        # Step 1: Get the raw JSON body from the request.
        payload_json = await request.json()
        
        # Step 2: Manually validate the JSON against our Pydantic model.
        # If this fails, the 'except' block will catch it.
        payload = models.PrometheusWebhookPayload.model_validate(payload_json)

    except ValidationError as e:
        # Step 3 (Failure): If validation fails, log the exact payload that caused the error.
        logging.error(f"Pydantic Validation Error: {e.errors()}")
        logging.error(f"--- FAILING PAYLOAD ---")
        logging.error(json.dumps(payload_json, indent=2))
        logging.error(f"-----------------------")
        # Return a clear error response.
        raise HTTPException(
            status_code=422,
            detail={"error": "Pydantic validation failed", "details": e.errors()}
        )
    except json.JSONDecodeError:
        # Handle cases where the request body isn't even valid JSON.
        body_bytes = await request.body()
        logging.error(f"Invalid JSON received: {body_bytes.decode()}")
        raise HTTPException(status_code=400, detail="Invalid JSON format.")

    # --- If validation succeeds, the original workflow continues ---
    initial_message = build_initial_message(payload)
    
    try:
        response = slack_client.chat_postMessage(
            channel="#test-on-call", 
            blocks=initial_message
        )
        thread_ts = response["message"]["ts"]
        
        # Start the background task for deeper analysis
        background_tasks.add_task(run_incident_workflow, str(uuid4()), payload, thread_ts)

    except Exception as e:
        logging.error(f"Failed to post to Slack or start background task: {e}")
        return {"status": "received_but_failed_downstream", "code": 200}
    
    return {"status": "received", "code": 200}


# Technically first thing would be to send an immediate alert to slack about issue
# First thing is using this context to search messages in slack channels to get some more context or see if a situation like this happened (STATE 1)
# Then look into documentation (STATE 2)
# Then get relevant runbooks/dashbooks to send back (STATE 3)
# Look into alertmanager alerting rules (STATE 4)
# send back to engineer all recordings for the alert(s) (after the initial message for just alerting a new alert came in)