from datetime import datetime
import os
import logging
from collections import deque

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

load_dotenv()

SECRET_TOKEN = os.environ["SECRET_TOKEN"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SIGN_IN_SECRET = os.environ["SIGN_IN_SECRET"]
app = FastAPI()
slack_app = App(token=SLACK_TOKEN, signing_secret=SIGN_IN_SECRET)
client = WebClient(token=SLACK_TOKEN)
logging.basicConfig(level=logging.INFO)
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
# for posting messages that can fade after a while
# response = client.chat_postEphemeral(
#     channel="C0XXXXXX",
#     text="Hello silently from your app! :tada:",
#     user="U0XXXXXXX"
# )

model_response_history = []


def get_incident_id(payload: models.WebhookPayload):

    event_data = payload.event.data
    if isinstance(event_data, models.IncidentData):
        logging.info(f"Found IncidentData with ID: {event_data.id}")
        return event_data.id

    logging.warning(
        f"Webhook event is of type '{type(event_data).__name__}', not IncidentData. No incident ID available.")
    return None


def send_slack_alert(payload: models.WebhookPayload):
    incident_id = get_incident_id(payload)
    incident_details = webhook_to_event_payload(payload)
    if not incident_id or not incident_details:
        logging.info("Webhook is not an incident event. Skipping Slack notification.")

    try:
        blocks = build_slack_blocks(incident_details)
        notification_text = format_event_payload(incident_details)
        response = client.chat_postMessage(
            channel="#test-on-call",
            text=notification_text,
            blocks=blocks
        )
        thread_ts = response["message"]["ts"]
        channel_id = response["channel"]
        redis_client.hset(f"incident:{incident_id}", mapping={"channel-id": channel_id,
                                                              "thread-ts": thread_ts, "details": incident_details})
        redis_client.set(f"thread:{thread_ts}", str(incident_id))
        return response.status_code, response.data
    except SlackApiError as e:
        assert e.response["error"]
        logging.error(e.response)

history = [] # should be a database

def add_to_alert_history(payload: models.PrometheusAlert):

    start = datetime.fromisoformat(payload.startsAt.replace('Z', '+00:00'))
    end = datetime.fromisoformat(payload.endsAt.replace('Z', '+00:00'))
    prome_event = models.PrometheusAlert(status=payload.status, labels=payload.labels, annotations=payload.annotations, startsAt=start, endsAt=end, generatorURL=payload.generatorURL)
    history.append(prome_event)



@app.post('/webhook/prome')
async def promethues_webhook(payload: models.PrometheusWebhookPayload, background_tasks: BackgroundTasks):

    for alert in payload.alerts:
        event_payload = prome_to_event_payload(alert)
        background_tasks.add_task(add_to_alert_history, alert)
        # send it to our AI pipeline
    
    return {"status": "recieved", "code": 200}

@app.post('/webhook')
async def webhook_listener(payload: models.WebhookPayload,
                           request: Request,
                           background_tasks: BackgroundTasks,
                           x_webhook_token: str = Header(...)):

    if x_webhook_token != "something_secret":
        raise HTTPException(status_code=403, detail="Invalid Token")

    background_tasks.add_task(send_slack_alert, payload)

    headers = dict(request.headers)
    logging.info(f"Received webhook with header: {headers}")
    logging.info(f"Received webhook data: {payload.model_dump()}")
    return {"status": "received", "code": 200}

@app.post('/slack/events')
@slack_app.event('app_mention')
async def converse(event, say):

    if "bot_id" in event:
        raise HTTPException(status_code=403, detail="This is a bot, not need to reply")

    text = event["text"]
    thread_ts = event["thread_ts"]

    incident_id = redis_client.get(f"thread:{thread_ts}")
    incident = redis_client.hgetall(f"incident:{incident_id}")
    details = incident.get("details")
    parsed_details = models.EventPayload.model_validate_json(details)

    services = yaml_to_dict()
    service_context = services.get('services', {}).get(parsed_details.source)
    runbook_url = service_context['runbooks'][0]['url']
    async with httpx.AsyncClient() as client_async:
        response = await client_async.get(runbook_url)
        data = response.text

    context = (f"You are an expert on-call engineering assistant. "
              f"Based ONLY on the following runbook, answer the user's question.\n\n"
              f"--- CONTEXT: RUNBOOK ---\n{data}\n--- END CONTEXT ---\n\n"
              f"Question: {text}")

    model_response = gemini.models.generate_content(model='gemini-2.0-flash-001', contents=context)

    model_response_history.append({"user": text, "assistant": model_response})
    say(text=model_response.text, thread_ts=thread_ts)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=os.getenv('PORT', 8080))

