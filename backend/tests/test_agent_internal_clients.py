"""Tests for backend/agents/clients/*.
"""
import os
import pytest
from agents.clients import JarvisInternalClient, TicketsInternalClient, AnalyticsInternalClient

VALID_JARVIS_TOKEN = os.environ.get("JARVIS_QUEUE_API_TOKEN", "test-jarvis-token")
VALID_TICKET_TOKEN = os.environ.get("INTERNAL_TICKET_API_TOKEN", "test-internal-token")
VALID_ANALYTICS_TOKEN = os.environ.get("INTERNAL_ANALYTICS_API_TOKEN", "test-analytics-token")


@pytest.mark.anyio
async def test_jarvis_client_methods():
    client = JarvisInternalClient(token="test-jarvis-token")
    # 1. Enqueue item
    res = await client.enqueue_item(
        source_agent="test_agent",
        item_type="test_type",
        payload={"note": "hello from client test"},
        priority=5,
    )
    assert res["status"] == "enqueued"
    item_id = res["item"]["id"]

    # 2. Get queue
    queue_res = await client.get_queue(source_agent="test_agent")
    assert any(i["id"] == item_id for i in queue_res["items"])

    # 3. Stats
    stats = await client.get_queue_stats()
    assert "pending" in stats

    # 4. Resolve via decision
    dec_res = await client.submit_decision(
        decision_type="test_decision",
        action={"type": "test_action"},
        reason="tested",
        queue_item_id=item_id,
    )
    assert dec_res["status"] == "recorded"


@pytest.mark.anyio
async def test_tickets_client_methods():
    client = TicketsInternalClient(token="test-internal-token")
    # 1. Stats
    stats = await client.get_ticket_stats()
    assert "total" in stats
    assert "open" in stats

    # 2. Create ticket
    t_res = await client.create_or_append_ticket(
        kind="bug",
        title="Client Test Bug",
        description="Testing ticket client",
        reporter_user_ids=["user_test_client"],
    )
    assert t_res["status"] == "reported"
    t_id = t_res["id"]

    # 3. Get ticket
    t_get = await client.get_ticket(t_id)
    assert t_get["id"] == t_id

    # 4. Patch ticket
    t_patch = await client.patch_ticket(t_id, status="triaged", agent_plan="Investigate payment service")
    assert t_patch["status"] == "triaged"


@pytest.mark.anyio
async def test_analytics_client_methods():
    client = AnalyticsInternalClient(token="test-analytics-token")
    # 1. Stats
    stats = await client.get_campaign_stats()
    assert "total" in stats

    # 2. Create campaign
    c_res = await client.create_campaign(
        title="Client Test Campaign",
        channel="buffer",
        content={"caption": "Testing analytics client"},
    )
    assert c_res["status"] == "created"
    c_id = c_res["campaign_id"]

    # 3. Get campaign
    c_get = await client.get_campaign(c_id)
    assert c_get["campaign"]["title"] == "Client Test Campaign"

    # 4. Patch campaign
    c_patch = await client.patch_campaign(c_id, status="published", external_post_id="buf_test")
    assert c_patch["campaign"]["status"] == "published"
