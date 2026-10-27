import json

import anyio
import pytest
from fastapi.testclient import TestClient

from urim.interfaces.mcp_server import create_server
from urim.interfaces.rest_api import create_app


@pytest.fixture(scope="module")
def client(bundles):
    return TestClient(create_app(bundles))


def test_rest_routes(client, engine):
    assert {lang["lang_code"] for lang in client.get("/languages").json()} == {"en", "ru"}

    r = client.get("/verses/1KGS.18.27", params={"lang": "ru"})
    assert r.status_code == 200 and r.json()["translation_dramatic"].startswith("В самый солнцепёк")
    assert client.get("/verses/KJV:1KGS.18.33").json()["verse_id"] == "1KGS.18.33"

    r = client.get("/entities/person.elisha", params={"at_verse": "1KGS.19.21"})
    assert [c["component_key"] for c in r.json()["components"]] == ["role"]

    day = engine.get_event("evt.1kgs_18.carmel_contest")
    r = client.get(
        "/timeline",
        params={
            "utes_start": day.utes_start,
            "utes_end": day.utes_end,
            "entity": ["group.prophets_of_baal"],
        },
    )
    assert "evt.1kgs_18.execution_at_kishon" in {
        e["event"]["event_id"] for e in r.json()["entries"]
    }

    r = client.get(
        "/events/evt.1kgs_19.farewell_feast/causal-chain", params={"direction": "upstream"}
    )
    assert "evt.1kgs_19.theophany_at_horeb" in {n["event_id"] for n in r.json()["nodes"]}
    assert client.get("/systems/sys.theophany").json()["instances"][0]["initiator"]["name"] == (
        "the LORD (YHWH)"
    )
    assert client.get("/chapters/1KGS/17").json()["verses"][0]["verse_id"] == "1KGS.17.1"
    assert client.get("/search", params={"q": "noon"}).json()


def test_rest_errors(client):
    assert client.get("/entities/person.nobody").status_code == 404
    assert client.get("/verses/1KGS.18.27", params={"lang": "xx"}).status_code == 404
    assert client.get("/verses/garbage").status_code == 404
    assert client.get("/timeline", params={"utes_start": 5, "utes_end": 1}).status_code == 400


def test_mcp_tools(bundles):
    server = create_server(bundles)

    async def run():
        names = [t.name for t in await server.list_tools()]
        result = await server.call_tool(
            "get_entity_dossier",
            {"entity_id": "person.elisha", "at_verse": "1KGS.19.19", "lang": "ru"},
        )
        return names, json.loads(result.content[0].text)

    names, dossier = anyio.run(run)
    assert names == [
        "get_verse_matrix",
        "get_chapter_stream",
        "get_entity_dossier",
        "get_system_codex",
        "query_timeline",
        "trace_causal_chain",
        "semantic_search",
    ]
    assert dossier["canonical_name"] == "Елисей"
    assert dossier["components"][0]["label_value"] == "Богатый землевладелец (12 пар волов)"
