from datetime import datetime
import os
import yaml
from models import EventPayload, EventSeverity, PrometheusAlert, PrometheusWebhookPayload


def yaml_to_dict():
    file = None
    with open("services.yaml") as f:
        file = f.read()

    yaml_dict = yaml.safe_load(file)
    return yaml_dict

# def webhook_to_event_payload(payload: WebhookPayload):

#     event_data = payload.event.data

#     if isinstance(event_data, IncidentData):
#         severity = getattr(event_data, 'severity', EventSeverity.INFO)

#         event_payload = EventPayload(
#             id=str(event_data.id),
#             summary=event_data.title,
#             severity=severity,
#             source=event_data.service.summary,
#             timestamp=payload.event.occurred_at)

#         return event_payload
#     return None

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

def build_initial_message(event_payload: PrometheusWebhookPayload):
    status = event_payload.status

    if status == "resolved":
        return [{
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"✅ Issue Resolved: {event_payload.groupLabels.get('alertname')}",
                "emoji": True
            }
        }]

    group_labels_str = str(event_payload.groupLabels)
    common_labels_str = str(event_payload.commonLabels)
    common_annotations_str = str(event_payload.commonAnnotations)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔥 {len(event_payload.alerts)} Prometheus Alert(s): Firing",
                "emoji": True
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Group Labels:*\n`{group_labels_str}`"},
                {"type": "mrkdwn", "text": f"*Common Labels:*\n`{common_labels_str}`"},
                {"type": "mrkdwn", "text": f"*Common Annotations:*\n`{common_annotations_str}`"}
            ]
        },
        {"type": "divider"},
        {
            # FIX: This block is now a valid context block structure.
            # It expects an 'elements' key with a list of text/mrkdwn objects.
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🔎 I am now investigating this alert..."
                }
            ]
        }
    ]

    return blocks


def prome_to_event_payload(alert: PrometheusAlert):
    
    severity = alert.labels.get('severity', EventSeverity.INFO)
    summary = alert.annotations.get('summary', 'No summary provided')
    source = alert.labels.get('service', 'unknown-service')

    return EventPayload(id=alert.labels.get('alertname'),
                        summary=summary,
                        severity=severity,
                        source=source,
                        timestamp=datetime.fromisoformat(alert.startsAt.replace('Z', '+00:00')), # make sure this is a datetime
                        component=alert.labels.get('job'),
                        class_=alert.labels.get('alertname'))


def check_service_yaml(
    service_name: str,
    file_path: str = "src/services.yaml",
    new_runbooks: list = None,
    new_dashboards: list = None):

    data = {}
    file_existed = os.path.exists(file_path)

    if file_existed:
        try:
            with open(file_path, 'r') as file:
                data = yaml.safe_load(file)
                if data is None: # Handle empty YAML file
                    data = {}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML from '{file_path}': {e}")
            return False
        except Exception as e:
            print(f"An unexpected error occurred while reading '{file_path}': {e}")
            return False

    if 'services' not in data or not isinstance(data['services'], dict):
        data['services'] = {}


    if service_name not in data['services'] or not isinstance(data['services'][service_name], dict):
        data['services'][service_name] = {}

    service_config = data['services'][service_name]
    updated = False 

    if 'runbooks' not in service_config or not isinstance(service_config['runbooks'], list):
        service_config['runbooks'] = []
        updated = True

    if new_runbooks:
        for new_rb in new_runbooks:
            found = False
            for existing_rb in service_config['runbooks']:
                if existing_rb.get('name') == new_rb.get('name') and \
                   existing_rb.get('url') == new_rb.get('url'):
                    found = True
                    break
            if not found:
                service_config['runbooks'].append(new_rb)
                updated = True
                print(f"Added runbook: {new_rb.get('name')} to service '{service_name}'")

    if 'dashboards' not in service_config or not isinstance(service_config['dashboards'], list):
        service_config['dashboards'] = []
        updated = True

    if new_dashboards:
        for new_db in new_dashboards:
            found = False
            for existing_db in service_config['dashboards']:
                if existing_db.get('name') == new_db.get('name') and \
                   existing_db.get('url') == new_db.get('url'):
                    found = True
                    break
            if not found:
                service_config['dashboards'].append(new_db)
                updated = True
                print(f"Added dashboard: {new_db.get('name')} to service '{service_name}'")

    # Write back to file only if changes were made
    if updated or not file_existed: # If file didn't exist, we created structure, so write it
        try:
            with open(file_path, 'w') as file:
                yaml.dump(data, file, default_flow_style=False, sort_keys=False, indent=2)
            print(f"File '{file_path}' {'updated' if updated else 'created'} successfully.")
            return True
        except Exception as e:
            print(f"Error writing to YAML file '{file_path}': {e}")
            return False
    else:
        print(f"No changes needed for file '{file_path}'.")
        return True