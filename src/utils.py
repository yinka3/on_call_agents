import yaml
from models import EventPayload, EventSeverity, WebhookPayload, IncidentData


def yaml_to_dict():
    file = None
    with open("services.yaml") as f:
        file = f.read()

    yaml_dict = yaml.safe_load(file)
    return yaml_dict

def webhook_to_event_payload(payload: WebhookPayload):

    event_data = payload.event.data

    if isinstance(event_data, IncidentData):
        severity = getattr(event_data, 'severity', EventSeverity.INFO)

        event_payload = EventPayload(
            id=str(event_data.id),
            summary=event_data.title,
            severity=severity,
            source=event_data.service.summary,
            timestamp=payload.event.occurred_at)

        return event_payload
    return None

def format_event_payload(event_payload: EventPayload) -> str:
    return (f"Incident: {event_payload.summary}, Severity: {event_payload.severity.value}, "
            f"Source: {event_payload.source}")



def build_slack_blocks(event_payload: EventPayload) -> list:
    """
    Constructs a Slack Block Kit message with a theme based on severity.
    """
    # 1. Determine the theme based on the severity
    if event_payload.severity == EventSeverity.CRITICAL or event_payload.severity == EventSeverity.ERROR:
        header_icon = "🔥"
    elif event_payload.severity == EventSeverity.WARNING:
        header_icon = "⚠️"
    else: # Info
        header_icon = "ℹ️"

    services = yaml_to_dict()
    service_context = services.get('services', {}).get(event_payload.source)
    ts_unix = int(event_payload.timestamp.timestamp())
    formatted_ts = f"<!date^{ts_unix}^{{date_num}} {{time_secs}}|{event_payload.timestamp.isoformat()}>"


    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{header_icon} {event_payload.summary}",
                "emoji": True
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n`{event_payload.severity.value}`"},
                {"type": "mrkdwn", "text": f"*Timestamp:*\n{formatted_ts}"},
                {"type": "mrkdwn", "text": f"*Source:*\n{event_payload.source}"},
                {"type": "mrkdwn", "text": f"*Component:*\n`{event_payload.component}`"}
            ]}
    ]

    if service_context:
        blocks.append({"type": "divider"})

        runbooks = service_context.get('runbooks', [])
        if runbooks:
            runbooks_links = []
            for books in runbooks:
                runbooks_links.append(f"• <{books.get('url')}|{books.get('name')}>")

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📖 *Relevant Runbooks*\n" + "\n".join(runbooks_links)}
            })

        dashboards = service_context.get('dashboards', [])
        if dashboards:
            dashboard_links = []
            for dash in dashboards:
                dashboard_links.append(f"• <{dash.get('url')}|{dash.get('name')}>")

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📊 *Relevant Dashboards*\n" + "\n".join(dashboard_links)}
            })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            { "type": "mrkdwn", "text": f"*Group:* {event_payload.group} | *Class:* {event_payload.class_}"}
        ]
    })
    return blocks

