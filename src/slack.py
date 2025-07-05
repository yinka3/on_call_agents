import time
import os
import logging
from typing import Any, Dict, List, Union
import chromadb
from slack_sdk import WebClient
from slack_bolt import App
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from google import genai
import redis
from chromadb.utils import embedding_functions
load_dotenv()

SECRET_TOKEN = os.environ["SECRET_TOKEN"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SIGN_IN_SECRET = os.environ["SIGN_IN_SECRET"]


slack_app = App(token=SLACK_TOKEN, signing_secret=SIGN_IN_SECRET)
slack_client = WebClient(token=SLACK_TOKEN)

logging.basicConfig(level=logging.INFO)

gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
chromadb_client = chromadb.PersistentClient("./chroma_db")
embedding_function = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
        api_key=os.environ["GEMINI_API_KEY"], task_type="RETRIEVAL_DOCUMENT")

def search_documentation(query_text, n_results: int = 3):
    pass

def get_or_create_chroma_db(documents_to_embed: Union[None, Any], collection_name: str, metadata: Union[None, Any] = None, db_ids: Union[None, Any] = None):
    collection = chromadb_client.get_or_create_collection(
        name=collection_name, 
        embedding_function=embedding_function
    )

    if not documents_to_embed:
        logging.warning("No documents provided to embed.")
        return collection

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
            messages = history.data.get("messages", [])

            for message in messages:
                thread_ts = message.get("thread_ts")
                if thread_ts and thread_ts not in processed_thread_ts:
                    processed_thread_ts.add(thread_ts)

                    time.sleep(1)
                    thread_replies = slack_client.conversations_replies(
                            channel=channel_name,
                            ts=thread_ts)

                    thread_messages = thread_replies.data.get("messages", [])
                    if not thread_messages:
                        continue 
                    
                    parent_message = thread_messages[0]
                    reply_texts = [reply.get("text", "") for reply in thread_messages[1:]]
                    reply_string = "\n".join(reply_texts)
                    full_message = {
                        "user": parent_message.get("user"),
                        "text": parent_message.get("text"),
                        "ts": parent_message.get("ts"),
                        "is_thread_parent": True,
                        "replies": reply_string
                    }
                    data.append(full_message)
                elif not thread_ts:
                    data.append({
                        "user": message.get("user"),
                        "text": message.get("text"),
                        "ts": message.get("ts"),
                        "is_thread_parent": True,
                        "replies": ""
                    })

            # Check if there are more pages of messages to fetch
            if history.data.get("has_more"):
                cursor = history.data["response_metadata"]["next_cursor"]
                time.sleep(1)
            else:
                break
            
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 10))
                logging.warning(f"Rate limited by Slack. Retrying in {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            else:
                logging.error(f"Slack API Error: {e.response['error']}. Check if channel ID is correct and bot is in the channel.")
                break
        except KeyError as e:
            print(f"KeyError processing message: {e}")
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
        metadatas = results.get('metadatas', [[]])[0]

        for i, meta in enumerate(metadatas):

            user = meta.get('user', 'unknown_user')
            
            # The 'text' in the metadata is the original parent message
            original_message = meta.get('text', 'Could not retrieve message text.') 
            
            # You could add a permalink here in the future if you store it
            formatted_results.append(f"• *From User {user}:* \"{original_message}\"")

        return formatted_results
    except Exception as e:
        logging.error(f"Failed to query ChromaDB collection 'slack_messages': {e}")
        return []



# if __name__ == "__main__":
#     # Replace with the name of a real channel in your Slack workspace
#     channel_name = "#on-call-engineers" 
#     print(f"Fetching history from channel: {channel_name}...")
#     format_slack_message_history("C093SNFR555")
#     print("Done.")
#     time.sleep(15)