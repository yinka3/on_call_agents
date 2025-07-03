from datetime import datetime
import json
import os
from typing import Any, Optional
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from flask import app
import redis
import models
from utils import build_initial_message, prome_to_event_payload
from google import genai
from google.genai import types
import chromadb
from chromadb import EmbeddingFunction, Embeddings
from slack import search_slack_history, slack_client
from utils import prome_to_event_payload, build_slack_blocks

load_dotenv()
app = FastAPI()
chromadb_client = chromadb.Client()
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input):
        embedded_model = 'models/gemini-embedding-exp-03-07'
        out = gemini.models.embed_content(model=embedded_model, contents=input, 
                                          config={types.EmbedContentConfig(task_type="semantic_similarity")})

        return out.embeddings


def get_or_create_chroma_db(documents: None | models.PrometheusAlert, name):
    collection = chromadb_client.get_or_create_collection(name=name, embedding_function=GeminiEmbeddingFunction())

    if len(documents) > 1:
        for i, doc in enumerate(documents):
            collection.add(documents=doc, ids=f"id{i}")
    elif len(documents) == 1:
        collection.add()
    
    return collection


def run_incident_workflow(id: str, payload: models.PrometheusWebhookPayload, thread_ts):

    alert_fingerprints = []
    for alert in payload.alerts:
        alert_fingerprints.append(alert.fingerprint)
        redis_client.set(f"prometheus:alert:{alert.fingerprint}", alert.model_dump_json(indent=2), ex=7200)
    
    if alert_fingerprints:
        redis_client.sadd(f"payload:{id}", *alert_fingerprints)
        redis_client.expire(f"payload:{id}", 7200)
    redis_client.set(f"incident:{id}:thread_ts", thread_ts)
    summary = summary_on_alerts(id)

    return summary

# gets context, gets llm response and then embeds it and stores it, this should definitely go into a redis db
def summary_on_alerts(payload_id: Optional[str]):
    
    alerts_fingerprints = redis_client.smembers(f"payload:{payload_id}")
    if not alerts_fingerprints:
        return

    alert_keys = [f"prometheus:alert:{fp.decode('utf-8')}" for fp in alerts_fingerprints]
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

    llm_reponse = get_hallucinated_context(llm_context)
    get_embeddings = GeminiEmbeddingFunction(llm_reponse)
    redis_client.hset(key=f"Payload:{payload_id}", value={"llm_context": llm_context, "llm_reponse": llm_reponse, "embeddings": get_embeddings})
    return {"llm_context": llm_context, "llm_reponse": llm_reponse, "embeddings": get_embeddings}


def get_hallucinated_context(context):
    if not context:
        raise ValueError("There should be some context available")
    
    model_response = gemini.models.generate_content(model='gemini-2.0-flash-001', contents=context)
    return model_response.text



@app.post('/webhook/prome')
async def promethues_webhook(payload: models.PrometheusWebhookPayload, background_tasks: BackgroundTasks):
    initial_message = build_initial_message(payload)
    response = slack_client.chat_postMessage("#test-on-call", blocks=initial_message)
    thread_ts = response["message"]["ts"]
    background_tasks.add_task(run_incident_workflow, str(uuid4()), payload, thread_ts)
    
    return {"status": "recieved", "code": 200}


# Technically first thing would be to send an immediate alert to slack about issue
# First thing is using this context to search messages in slack channels to get some more context or see if a situation like this happened (STATE 1)
# Then look into documentation (STATE 2)
# Then get relevant runbooks/dashbooks to send back (STATE 3)
# Look into alertmanager alerting rules (STATE 4)
# send back to engineer all recordings for the alert(s) (after the initial message for just alerting a new alert came in)