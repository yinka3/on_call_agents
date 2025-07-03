from datetime import datetime
import os
import logging
from collections import deque
from typing import Any, Dict, List

import chromadb
import httpx
import uvicorn
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from slack_sdk import WebClient
from slack_bolt import App
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from google import genai
from google.genai import types
import redis
import models
from utils import build_slack_blocks, format_event_payload, prome_to_event_payload, webhook_to_event_payload, yaml_to_dict
from chromadb.utils import embedding_functions
load_dotenv()

SECRET_TOKEN = os.environ["SECRET_TOKEN"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SIGN_IN_SECRET = os.environ["SIGN_IN_SECRET"]


app = FastAPI()

slack_app = App(token=SLACK_TOKEN, signing_secret=SIGN_IN_SECRET)
slack_client = WebClient(token=SLACK_TOKEN)

logging.basicConfig(level=logging.INFO)

gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

chromadb_client = chromadb.PersistentClient("./chroma_db")
embedding_function = embedding_functions.GoogleGenerativeAIEmbeddingFunction(
        api_key=os.environ["GEMINI_API_KEY"], task_type="RETRIEVAL_QUERY")

def get_or_create_chroma_db(documents_to_embed: None | Any, name, metadata, db_ids):
    collection = chromadb_client.get_or_create_collection(name, embedding_function)

    collection.upsert(
        documents=documents_to_embed,
        metadatas=metadata,
        ids=db_ids
    )
    
    return collection

def format_document_text(message_data: Dict) -> str:
    """
    Creates a single string from a message object for embedding.
    This string is what the vector search will be performed on.
    """

    parent_text = message_data.get("text", "")
    replies = "\n".join(message_data.get("replies", []))

    full_text = f"From user {message_data.get('user')}: {parent_text}"
    if replies:
        full_text += f"\n---REPLIES---\n{replies}"
        
    return full_text

def format_slack_message_history(channel_name: str):
    data: List[Dict] = []
    processed_thread_ts = set()
    
    cursor = None
    while True:
        try:
            history = slack_client.conversations_history(channel=channel_name, cursor=cursor)
            messages = history.data["messages"]

            for message in messages:
                thread_ts = message.get("thread_ts")
                if thread_ts and thread_ts not in processed_thread_ts:
                    processed_thread_ts.add(thread_ts)
                    thread_replies = slack_client.conversations_replies(
                            channel=channel_name,
                            ts=thread_ts)

                    thread_messages = thread_replies.data["messages"]
                    if not thread_messages:
                        continue 
                    
                    parent_message = thread_messages[0]
                    reply_texts = [reply.get("text") for reply in thread_messages[1:]]

                    full_message = {
                        "user": parent_message.get("user"),
                        "text": parent_message.get("text"),
                        "ts": parent_message.get("ts"),
                        "is_thread_parent": True,
                        "replies": reply_texts
                    }
                    data.append(full_message)
                elif not message["thread_ts"]:
                    data.append({
                        "user": message.get("user"),
                        "text": message.get("text"),
                        "ts": message.get("ts"),
                        "is_thread_parent": True,
                        "replies": []
                    })

            # Check if there are more pages of messages to fetch
            if history.data.get("has_more"):
                cursor = history.data["response_metadata"]["next_cursor"]
            else:
                break
        except SlackApiError as e:
            print({e})
            break
        except KeyError as e:
            print(f"KeyError processing message: {e} - Message: {message}")
            continue
    
    if not data:
        print("No new messages to add.")
        return
    
    documents_to_embed = [format_document_text(msg) for msg in data]
    ids_to_use = [msg["ts"] for msg in data]
    print(f"Adding {len(documents_to_embed)} documents to ChromaDB collection: slack_messages")
    get_or_create_chroma_db(documents_to_embed, "slack_messages", data, ids_to_use)


def search_slack_history(query_text: str, n_results: int = 3):
    try:
        slack_collection = chromadb_client.get_collection(
            name="slack_messages",
            embedding_function=embedding_function 
        )

        results = slack_collection.query(
            query_texts=[query_text],
            n_results=n_results
        )

        formatted_results = []
        documents = results.get('documents', [[]])[0]
        metadatas = results.get('metadatas', [[]])[0]

        for i, doc_text in enumerate(documents):
            meta = metadatas[i]
            user = meta.get('user', 'unknown_user')
            
            # The 'text' in the metadata is the original parent message
            original_message = meta.get('text', doc_text) 
            
            # You could add a permalink here in the future if you store it
            formatted_results.append(f"• *From User {user}:* \"{original_message}\"")

        return formatted_results
    except Exception as e:
        return []

# will update this to take in promethesus payload instead of a weebhook payload
# def get_incident_id(payload: models.WebhookPayload):

#     event_data = payload.event.data
#     if isinstance(event_data, models.IncidentData):
#         logging.info(f"Found IncidentData with ID: {event_data.id}")
#         return event_data.id

#     logging.warning(
#         f"Webhook event is of type '{type(event_data).__name__}', not IncidentData. No incident ID available.")
#     return None

# will update this to take in promethesus payload instead of a weebhook payload
# def send_slack_alert(payload: models.WebhookPayload):
#     incident_id = get_incident_id(payload)
#     incident_details = webhook_to_event_payload(payload)
#     if not incident_id or not incident_details:
#         logging.info("Webhook is not an incident event. Skipping Slack notification.")

#     try:
#         blocks = build_slack_blocks(incident_details)
#         notification_text = format_event_payload(incident_details)
#         response = slack_client.chat_postMessage(
#             channel="#test-on-call",
#             text=notification_text,
#             blocks=blocks
#         )
#         thread_ts = response["message"]["ts"]
#         channel_id = response["channel"]
#         redis_client.hset(f"incident:{incident_id}", mapping={"channel-id": channel_id,
#                                                               "thread-ts": thread_ts, "details": incident_details})
#         redis_client.set(f"thread:{thread_ts}", str(incident_id))
#         return response.status_code, response.data
#     except SlackApiError as e:
#         assert e.response["error"]
#         logging.error(e.response)




# @app.post('/slack/events')
# @slack_app.event('app_mention')
# async def converse(event, say):

#     if "bot_id" in event:
#         raise HTTPException(status_code=403, detail="This is a bot, not need to reply")

#     text = event["text"]
#     thread_ts = event["thread_ts"]

#     incident_id = redis_client.get(f"thread:{thread_ts}")
#     incident = redis_client.hgetall(f"incident:{incident_id}")
#     details = incident.get("details")
#     parsed_details = models.EventPayload.model_validate_json(details)

#     services = yaml_to_dict()
#     service_context = services.get('services', {}).get(parsed_details.source)
#     runbook_url = service_context['runbooks'][0]['url']
#     async with httpx.AsyncClient() as client_async:
#         response = await client_async.get(runbook_url)
#         data = response.text

#     context = (f"You are an expert on-call engineering assistant. "
#               f"Based ONLY on the following runbook, answer the user's question.\n\n"
#               f"--- CONTEXT: RUNBOOK ---\n{data}\n--- END CONTEXT ---\n\n"
#               f"Question: {text}")

#     model_response = gemini.models.generate_content(model='gemini-2.0-flash-001', contents=context)


