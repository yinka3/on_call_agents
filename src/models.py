from __future__ import annotations
from typing import Optional, List, Dict, Union
from datetime import datetime
from pydantic import BaseModel, Field, AnyHttpUrl
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
    severity: Union[EventSeverity, str]
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

# -------------------------------------Promethesues-----------------------------------------------------------

class PrometheusAlert(BaseModel):
    status: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    startsAt: str
    endsAt: str
    generatorURL: Optional[str]
    fingerprint: Optional[str]

class PrometheusWebhookPayload(BaseModel):
    version: str
    groupKey: str
    truncatedAlerts: int
    status: str
    receiver: str
    groupLabels: Dict[str, str]
    commonLabels: Dict[str, str]
    commonAnnotations: Dict[str, str]
    externalURL: str
    alerts: List[PrometheusAlert]



