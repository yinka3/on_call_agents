from __future__ import annotations
from typing import Optional, List, Dict, Union, Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, AnyHttpUrl, RootModel
from enum import Enum

#might not even need all of these

class EventSeverity(str, Enum):
    CRITICAL = 'critical'
    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'

class EventAction(str, Enum):
    TRIGGER = 'trigger'
    ACKNOWLEDGE = 'acknowledge'
    RESOLVE = 'resolve'

class EventLink(BaseModel):
    href: AnyHttpUrl
    text: Optional[str] = None

class EventImage(BaseModel):
    src: AnyHttpUrl
    href: Optional[AnyHttpUrl] = None
    alt: Optional[str] = None

class EventPayload(BaseModel):
    id: str
    summary: str
    severity: EventSeverity
    source: str
    timestamp: Optional[datetime] = None
    component: Optional[str] = None
    group: Optional[str] = None
    class_: Optional[str] = None
    custom_details: Optional[Dict[str, str]] = None

class EventRequest(BaseModel):
    routing_key: str = Field(..., min_length=32, max_length=32)
    event_action: EventAction
    dedup_key: Optional[str] = Field(None, max_length=255)

    # The payload is required for 'trigger' events.
    # For 'acknowledge' and 'resolve', it can be omitted.
    payload: Optional[EventPayload] = None

    # Optional top-level fields
    client: Optional[str] = None
    client_url: Optional[AnyHttpUrl] = None
    links: Optional[List[EventLink]] = None
    images: Optional[List[EventImage]] = None

    def model_dump(self, *args, **kwargs):
        # Pydantic's `by_alias=True` is crucial for the 'class' field.
        kwargs.setdefault('by_alias', True)
        # Exclude None values to create a cleaner JSON payload.
        kwargs.setdefault('exclude_none', True)
        return super().model_dump(*args, **kwargs)

# ----------------------------------------Webhook Payloads--------------------------------------------
class WebhookEventType(str, Enum):
    INCIDENT_TRIGGERED = "incident.triggered"
    INCIDENT_ACKNOWLEDGED = "incident.acknowledged"
    INCIDENT_UNACKNOWLEDGED = "incident.unacknowledged"
    INCIDENT_RESOLVED = "incident.resolved"
    INCIDENT_REASSIGNED = "incident.reassigned"
    INCIDENT_ANNOTATED = "incident.annotated"
    INCIDENT_ESCALATED = "incident.escalated"
    INCIDENT_DELEGATED = "incident.delegated"
    INCIDENT_PRIORITY_UPDATED = "incident.priority_updated"
    INCIDENT_RESPONDER_ADDED = "incident.responder.added"
    INCIDENT_RESPONDER_REPLIED = "incident.responder.replied"
    INCIDENT_STATUS_UPDATE_PUBLISHED = "incident.status_update_published"
    SERVICE_CREATED = "service.created"
    SERVICE_UPDATED = "service.updated"
    SERVICE_DELETED = "service.deleted"
    PAGEY_PING = "pagey.ping"  # for a test event

class WebhookReference(BaseModel):
    id: UUID
    type: str
    summary: Optional[str] = None
    self: Optional[AnyHttpUrl] = None
    html_url: Optional[AnyHttpUrl] = None

class BaseWebhookData(BaseModel):
    id: UUID
    type: Optional[str]

class IncidentData(BaseWebhookData):
    type: Literal["incident"]
    incident_number: int
    title: str
    status: str
    summary: Optional[str] = None
    service: WebhookReference
    assignments: List
    escalation_policy: WebhookReference

class IncidentNoteData(BaseWebhookData):
    type: Literal["incident_note"]
    content: str
    user: WebhookReference
    incident: WebhookReference

class ServiceData(BaseWebhookData):
    type: Literal["service"]
    name: str
    description: Optional[str] = None
    status: str

class PageyPingData(BaseModel):
    type: Literal["ping"]
    message: str

class WebhookClient(BaseModel):
    name: str
    href: Optional[AnyHttpUrl] = None

class WebhookData(RootModel[Union[IncidentData, IncidentNoteData, ServiceData, PageyPingData]]):
    pass

class WebhookEvent(BaseModel):
    id: UUID
    event_type: WebhookEventType
    resource_type: str
    occurred_at: datetime
    agent: Optional[WebhookReference] = None
    client: Optional[WebhookClient] = None
    data: WebhookData

class WebhookPayload(BaseModel):
    event: Optional[WebhookEvent] = None
    messages: Optional[List[WebhookEvent]] = None

#-----------------------------------Webhook Subscriptions Models-----------------------------------------------------

class WebhookFilterType(str, Enum):
    ACCOUNT_REFERENCE = "account_reference"
    SERVICE_REFERENCE = "service_reference"
    TEAM_REFERENCE = "team_reference"

class WebhookFilter(BaseModel):
    # 'id' is required for service_reference and team_reference
    id: Optional[str] = None
    type: WebhookFilterType

class CustomHeader(BaseModel):
    name: str
    value: str

class WebhookDeliveryMethod(BaseModel):
    type: Literal["http_delivery_method"]
    url: AnyHttpUrl
    custom_header: Optional[List[CustomHeader]] = None

class WebhookSubscription(BaseModel):
    type: Literal["webhook_subscription"] = "webhook_subscription"
    description: Optional[str] = None
    events: List[str] = Field(..., min_length=1)
    filter: WebhookFilter
    delivery_method: WebhookDeliveryMethod
    active: bool = True

class CreateWebhookSubscriptionRequest(BaseModel):
    webhook_subscription: WebhookSubscription

