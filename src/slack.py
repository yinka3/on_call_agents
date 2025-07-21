import time
import os
import logging
from typing import Dict, List
from slack_sdk import WebClient
from slack_bolt import App
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from chroma import chromadb_client, get_or_create_chroma_db, embedding_func
from gemini import GeminiEmbeddingFunction
load_dotenv()

SECRET_TOKEN = os.environ["SECRET_TOKEN"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SIGN_IN_SECRET = os.environ["SIGN_IN_SECRET"]


slack_app = App(token=SLACK_TOKEN, signing_secret=SIGN_IN_SECRET)
retry_handler = RateLimitErrorRetryHandler(max_retry_count=3)
slack_client = WebClient(token=SLACK_TOKEN, retry_handlers=[retry_handler])

logging.basicConfig(level=logging.INFO)

def format_document_text(message_data: Dict) -> str:
    """Creates a single string from a message object for embedding."""
    parent_text = message_data.get("text", "")
    replies = "\n".join(message_data.get("replies", []))

    full_text = f"From user {message_data.get('user')}: {parent_text}"
    if replies:
        full_text += f"\n---REPLIES---\n{replies}"
    return full_text

def fetch_and_process_channel_messages(channel_id: str) -> List[Dict]:
    """
    Fetches all messages from a channel, processes threads, and formats the output.
    The RetryHandler on the slack_client will automatically handle rate limits.
    """
    data: List[Dict] = []
    processed_thread_ts = set()
    cursor = None

    while True:
        try:
            history = slack_client.conversations_history(channel=channel_id, cursor=cursor)
            messages = history.data.get("messages", [])

            for message in messages:
                thread_ts = message.get("thread_ts")
                if thread_ts and thread_ts not in processed_thread_ts:
                    processed_thread_ts.add(thread_ts)

                    thread_replies = slack_client.conversations_replies(
                        channel=channel_id,
                        ts=thread_ts
                    )

                    thread_messages = thread_replies.data.get("messages", [])
                    if not thread_messages:
                        continue
                    parent_message = thread_messages[0]
                    reply_texts = [reply.get("text", "") for reply in thread_messages[1:]]
                    data.append({
                        "user": parent_message.get("user"),
                        "text": parent_message.get("text"),
                        "ts": parent_message.get("ts"),
                        "replies": "\n".join(reply_texts)
                    })
                elif not thread_ts:
                    data.append({
                        "user": message.get("user"),
                        "text": message.get("text"),
                        "ts": message.get("ts"),
                        "replies": ""
                    })

            if not history.data.get("has_more"):
                break
            cursor = history.data["response_metadata"]["next_cursor"]

        except SlackApiError as e:
            logging.error(f"Slack API Error (non-rate-limit): {e.response['error']}")
            break
        except KeyError as e:
            print(f"KeyError processing message: {e}")
            continue
    return data


def sync_slack_history_to_chroma(channel_id: str, collection_name: str = "slack_messages"):
    """Orchestrates fetching messages and storing them in ChromaDB."""
    messages = fetch_and_process_channel_messages(channel_id)

    if not messages:
        logging.info("No new messages to add.")
        return

    documents_to_embed = [format_document_text(msg) for msg in messages]
    ids_to_use = [msg["ts"] for msg in messages]

    print(f"Adding {len(documents_to_embed)} documents to ChromaDB collection: {collection_name}")
    get_or_create_chroma_db(documents_to_embed, collection_name, messages, ids_to_use)


def search_slack_history(query_text: str, n_results: int = 3):
    query_embedding_func = GeminiEmbeddingFunction(task_type="retrieval_query")
    try:
        slack_collection = chromadb_client.get_collection(
            name="slack_messages",
            embedding_function=query_embedding_func 
        )

        results = slack_collection.query(
            query_texts=[query_text],
            n_results=n_results
        )

        formatted_results = []
        metadatas = results.get('metadatas', [[]])[0]

        for meta in metadatas:

            user = meta.get('user', 'unknown_user')
            
            original_message = meta.get('text', 'Could not retrieve message text.') 
            
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