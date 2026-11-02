import json
import atexit
import echo_assistant
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

_db_dir = tempfile.TemporaryDirectory(prefix="echo-site-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_db_dir.name, "test.db").replace("\\", "/")
os.environ.pop("FREELLMAPI_API_KEY", None)

import main
from echo_assistant import (
    EchoError, MissingAIConfiguration, SessionStore, interpret,
    resolve_contextual_followup, validate_intent,
)
from fastapi.testclient import TestClient

atexit.register(lambda: main.engine.dispose())


def future_time(days=30):
    return (datetime.now() + timedelta(days=days)).replace(microsecond=0).isoformat()


class EchoGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        main.echo_sessions = SessionStore(ttl_seconds=900)
        main._echo_rate.clear()
        with main.SessionLocal() as db:
            for model in (main.Registration, main.Requirement, main.Activity, main.Program, main.Student):
                db.query(model).delete()
            db.add_all([
                main.Activity(title="Explorer Night", category="Astronomy", venue="Science Hall",
                              start_time=future_time(10), end_time=future_time(10), status="Published"),
                main.Activity(title="Explorer Workshop", category="Technology", venue="Lab 2",
                              start_time=future_time(20), end_time=future_time(20), status="Ongoing"),
                main.Activity(title="Old Explorer Event", category="History", venue="Old Hall",
                              start_time=future_time(-20), end_time=future_time(-20), status="Completed"),
                main.Activity(title="Draft Explorer", category="Hidden", venue="Back Room",
                              start_time=future_time(5), end_time=future_time(5), status="Draft"),
                main.Activity(title="Robotics Showcase", category="Technology", venue="Auditorium",
                              start_time=future_time(40), end_time=future_time(40), status="Published"),
                main.Activity(title="Music Evening", category="Culture", venue="Main Stage",
                              start_time=future_time(50), end_time=future_time(50), status="Published"),
                main.Activity(title="Chess Open", category="Games", venue="Room 10",
                              start_time=future_time(60), end_time=future_time(60), status="Published"),
            ])
            db.commit()

    def intent(self, value):
        return patch("main.interpret", return_value=value)

    def post(self, text="hello", session="tab_alpha"):
        return self.client.post("/api/echo/command", json={"session_id": session, "transcript": text})

    def test_existing_website_serves_html(self):
        response = self.client.get("/website/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("loopIn", response.text)
        self.assertNotIn("loopIn College", response.text)

    def test_dashboard_has_isolated_campus_and_section_views(self):
        html = self.client.get("/website/").text
        for view_id in (
            "student-campus-subview", "student-map-subview", "student-events-subview",
            "student-contact-subview", "student-announcements-subview", "student-progress-subview",
        ):
            self.assertIn(f'id="{view_id}"', html)
        self.assertIn('id="student-campus-subview" class="student-subview campus-home"', html)
        self.assertIn('id="student-events-subview" class="student-subview hidden"', html)
        self.assertIn("~200 acres", html)
        self.assertIn("Established 2008", html)
        self.assertIn("Fully residential", html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("maps/search/?api=1&amp;query=BITS+Pilani+Hyderabad+Campus", html)

    def test_echo_client_prefers_detectable_device_voice_and_keeps_controls(self):
        source = self.client.get("/assets/echo-assistant.js").text
        self.assertIn("speechSynthesis.getVoices()", source)
        self.assertIn("voiceschanged", source)
        self.assertIn("utterance.rate = 0.94", source)
        self.assertIn("utterance.pitch = 1.0", source)
        self.assertIn("function stopSpeaking()", source)
        self.assertIn("function setMuted(value)", source)
        self.assertIn("recognition.onspeechend", source)
        self.assertIn("speechEndToTranscriptMs", source)
        self.assertIn("function handleLocalCommand", source)
        self.assertIn("function readServerTimings", source)

    def test_direct_navigation_and_scroll_controls_are_local(self):
        source = self.client.get("/assets/echo-assistant.js").text
        handler = source[source.index("function handleLocalCommand"):source.index("async function sendTranscript")]
        self.assertIn("scroll|move", handler)
        self.assertIn("go back|back|previous page", handler)
        self.assertIn("open|show|go to|navigate to|take me to", handler)
        self.assertLess(source.index("handleLocalCommand(transcript, timing)"), source.index("fetch(`${window.ECHO_API_BASE"))

    def test_existing_styles_and_script_are_served(self):
        self.assertEqual(self.client.get("/assets/style.css").status_code, 200)
        self.assertEqual(self.client.get("/assets/script.js").status_code, 200)
        self.assertEqual(self.client.get("/assets/echo-assistant.js").status_code, 200)

    def test_spatial_ui_assets_are_served_and_lightweight(self):
        contours = self.client.get("/assets/topography.svg")
        campus = self.client.get("/assets/campus-bh.webp")
        self.assertEqual(contours.status_code, 200)
        self.assertEqual(campus.status_code, 200)
        self.assertIn("image/svg+xml", contours.headers["content-type"])
        self.assertIn("image/webp", campus.headers["content-type"])
        self.assertLess(len(campus.content), 100_000)

    def test_topography_bundle_and_styles_are_served_without_stale_cache(self):
        bundle = self.client.get("/assets/topography-background.js")
        styles = self.client.get("/assets/topography-background.css")
        self.assertEqual(bundle.status_code, 200)
        self.assertIn("javascript", bundle.headers["content-type"])
        self.assertEqual(bundle.headers.get("cache-control"), "no-cache")
        self.assertIn("webgl2-ready", bundle.text)
        self.assertEqual(styles.status_code, 200)
        self.assertIn("text/css", styles.headers["content-type"])

    def test_public_demo_blocks_admin_personal_data_and_mutations(self):
        with patch.object(main, "PUBLIC_DEMO_MODE", True):
            self.assertEqual(self.client.post("/api/host/login", json={"email": "x", "password": "x"}).status_code, 404)
            self.assertEqual(self.client.get("/api/students/123").status_code, 404)
            self.assertEqual(self.client.post("/api/activities/1/register", json={}).status_code, 404)
            self.assertEqual(self.client.patch("/api/activities/1/status", json={}).status_code, 404)
            self.assertEqual(self.client.get("/api/activities/1?view=host").status_code, 404)
            self.assertEqual(self.client.get("/docs").status_code, 404)

    def test_public_demo_allows_site_echo_and_published_activity_reads_only(self):
        with patch.object(main, "PUBLIC_DEMO_MODE", True), self.intent({"intent": "answer", "text": "Hello from Echo."}):
            self.assertEqual(self.client.get("/website/").status_code, 200)
            self.assertEqual(self.client.get("/assets/echo-assistant.js").status_code, 200)
            self.assertEqual(self.client.get("/assets/topography.svg").status_code, 200)
            self.assertEqual(self.client.get("/assets/campus-bh.webp").status_code, 200)
            self.assertEqual(self.client.get("/assets/topography-background.js").status_code, 200)
            self.assertEqual(self.client.get("/assets/topography-background.css").status_code, 200)
            self.assertEqual(self.client.get("/api/activities").status_code, 200)
            response = self.client.post("/api/echo/command", json={"session_id": "public_test", "transcript": "hello"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["speech_text"], "Hello from Echo.")

    def test_public_demo_never_returns_draft_events(self):
        with patch.object(main, "PUBLIC_DEMO_MODE", True):
            response = self.client.get("/api/activities?status=Draft")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_public_demo_uses_stricter_echo_rate_limit(self):
        main._echo_rate.clear()
        with patch.object(main, "PUBLIC_DEMO_MODE", True), self.intent({"intent": "answer", "text": "Hello."}):
            for _ in range(5):
                self.assertEqual(self.post("hi", "public_rate_tab").status_code, 200)
            self.assertEqual(self.post("hi", "public_rate_tab").status_code, 429)

    def test_empty_text_is_rejected_before_ai(self):
        with self.intent({"intent": "answer", "text": "not called"}) as mocked:
            response = self.post("   ")
            self.assertEqual(response.status_code, 422)
            mocked.assert_not_called()

    def test_oversized_transcript_is_rejected(self):
        self.assertEqual(self.post("x" * 1001).status_code, 422)

    def test_missing_ai_configuration_is_clear(self):
        with patch("main.interpret", side_effect=MissingAIConfiguration("AI key is not configured.")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

    def test_ai_unavailable_returns_gateway_error_without_crashing_site(self):
        with patch("main.interpret", side_effect=EchoError("FreeLLMAPI is unavailable.")):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get("/api/activities").status_code, 200)

    def test_general_answer_returns_frontend_envelope(self):
        with self.intent({"intent": "answer", "text": "I can help. What are you working on?"}):
            response = self.post("I'm stuck")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"session_id", "speech_text", "action"})
        self.assertEqual(data["action"], {"action": "answer", "text": data["speech_text"]})

    def test_echo_route_returns_server_timing_without_prompt_or_session_data(self):
        with self.intent({"intent": "answer", "text": "I can help."}):
            response = self.post("I'm stuck", "timing_tab")
        header = response.headers.get("server-timing", "")
        self.assertIn("gateway;dur=", header)
        self.assertIn("action;dur=", header)
        self.assertNotIn("I'm stuck", header)
        self.assertNotIn("timing_tab", header)

    def test_followup_conversation_history_is_sent_to_ai(self):
        seen = []
        def fake_interpret(text, history, event_context):
            seen.append((text, list(history), list(event_context)))
            return {"intent": "answer", "text": "I can help with that."}
        with patch("main.interpret", side_effect=fake_interpret):
            self.post("I'm stuck", "history_tab")
            self.post("I cannot find the event page", "history_tab")
        self.assertEqual(len(seen[1][1]), 2)
        self.assertEqual(seen[1][1][0]["content"], "I'm stuck")

    def test_oversized_http_body_is_rejected(self):
        response = self.client.post("/api/echo/command", content=b" " * 9000,
                                    headers={"Content-Length": "9000", "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_event_search_uses_real_database_records(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            data = self.post("Find Explorer").json()
        self.assertEqual([item["title"] for item in data["action"]["results"]],
                         ["Explorer Night", "Explorer Workshop", "Old Explorer Event"])
        self.assertTrue(data["action"]["has_more"] is False)
        self.assertEqual(data["action"]["results"][2]["timing_status"], "Past")

    def test_verified_events_seed_only_into_disposable_database_and_deduplicate(self):
        with main.SessionLocal() as db:
            db.query(main.Activity).delete()
            db.commit()
        with patch.object(main, "DATABASE_URL", main._DISPOSABLE_DEMO_DATABASE_URL):
            self.assertEqual(main.seed_verified_disposable_demo_events(), 3)
            self.assertEqual(main.seed_verified_disposable_demo_events(), 0)
        listed = self.client.get("/api/activities").json()
        self.assertEqual(len(listed), 3)
        by_title = {event["title"]: event for event in listed}
        self.assertIn("VEDA 2026 — National Conference on Emerging Trends in Vacuum Electronic Devices & Applications", by_title)
        self.assertIn("ACEF 2027 — 8th Annual Conference on Economics and Finance", by_title)
        atmos = next(event for event in listed if event["title"].startswith("ATMOS 2026"))
        self.assertEqual(by_title["VEDA 2026 — National Conference on Emerging Trends in Vacuum Electronic Devices & Applications"]["status"], "Published")
        self.assertEqual(by_title["ACEF 2027 — 8th Annual Conference on Economics and Finance"]["start_time"], "2027-01-29")
        self.assertEqual(atmos["status"], "Completed")
        with main.SessionLocal() as db:
            atmos_row = db.query(main.Activity).filter(main.Activity.title.startswith("ATMOS 2026")).one()
            self.assertEqual(main._public_activity(atmos_row)["timing_status"], "Past")

    def test_disposable_seed_preserves_existing_records_and_fills_only_missing_events(self):
        with main.SessionLocal() as db:
            db.query(main.Activity).delete()
            db.add(main.Activity(
                title="VEDA 2026 — National Conference on Emerging Trends in Vacuum Electronic Devices & Applications",
                category="Academic conference", venue="BITS Pilani, Hyderabad Campus",
                start_time="2026-12-20", end_time="2026-12-22", status="Published",
                metadata_json=json.dumps({"official_source": "https://www.bits-pilani.ac.in/hyderabad/veda2026/"}),
            ))
            db.commit()
        with patch.object(main, "DATABASE_URL", main._DISPOSABLE_DEMO_DATABASE_URL):
            self.assertEqual(main.seed_verified_disposable_demo_events(), 2)
        with main.SessionLocal() as db:
            rows = db.query(main.Activity).all()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum("veda2026" in (row.metadata_json or "") for row in rows), 1)

    def test_seed_refuses_non_disposable_database_and_preserves_existing_events(self):
        with main.SessionLocal() as db:
            db.query(main.Activity).delete()
            db.add(main.Activity(title="Existing event", category="Campus", venue="Hall",
                                 start_time=future_time(), end_time=future_time(), status="Published"))
            db.commit()
        with patch.object(main, "DATABASE_URL", "sqlite:///team.db"):
            self.assertEqual(main.seed_verified_disposable_demo_events(), 0)
        with main.SessionLocal() as db:
            self.assertEqual([row.title for row in db.query(main.Activity).all()], ["Existing event"])

    def test_event_list_and_echo_search_share_the_verified_seeded_activity(self):
        with main.SessionLocal() as db:
            db.query(main.Activity).delete()
            db.commit()
        with patch.object(main, "DATABASE_URL", main._DISPOSABLE_DEMO_DATABASE_URL):
            self.assertEqual(main.seed_verified_disposable_demo_events(), 3)
        event_list = self.client.get("/api/activities").json()
        with self.intent({"intent": "search_events", "query": "VEDA 2026"}):
            echo_result = self.post("Find VEDA 2026").json()["action"]["results"]
        self.assertEqual(len(event_list), 3)
        self.assertEqual([item["activity_id"] for item in echo_result], [event_list[0]["id"]])
        self.assertEqual(echo_result[0]["timing_status"], "Upcoming")

    def test_event_counter_is_bound_to_the_api_results(self):
        html = self.client.get("/website/").text
        js = self.client.get("/assets/script.js").text
        self.assertIn('id="student-event-count"', html)
        self.assertIn("countBadge.textContent = `${events.length} total", js)
        self.assertIn("official_source", js)
        self.assertIn("istMidnightTimestamp", js)
        self.assertIn("getDateEventState", js)
        self.assertIn("Date countdown", js)
        self.assertIn("Math.max(0", js)

    def test_draft_events_are_never_search_results(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            response = self.post().json()
        self.assertNotIn("Draft Explorer", [item["title"] for item in response["action"]["results"]])

    def test_event_status_filter_uses_allowlist(self):
        with self.intent({"intent": "search_events", "query": "Explorer", "status": "Published"}):
            data = self.post().json()
        self.assertEqual([item["title"] for item in data["action"]["results"]], ["Explorer Night"])

    def test_upcoming_search_excludes_past_and_draft(self):
        with self.intent({"intent": "search_events", "query": "upcoming events", "upcoming": True}):
            data = self.post().json()
        titles = [item["title"] for item in data["action"]["results"]]
        self.assertNotIn("Old Explorer Event", titles)
        self.assertNotIn("Draft Explorer", titles)

    def test_search_does_not_return_unmatched_records(self):
        with self.intent({"intent": "search_events", "query": "NoSuchEvent"}):
            data = self.post().json()
        self.assertEqual(data["action"]["results"], [])
        self.assertIn("couldn't find", data["speech_text"])

    def test_followup_opens_selected_real_result(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            self.post("Find Explorer", "tab_open")
        with self.intent({"intent": "open_event", "result_index": 2}):
            data = self.post("Open the second one", "tab_open").json()
        self.assertEqual(data["action"]["event"]["title"], "Explorer Workshop")
        self.assertEqual(data["action"]["event"]["activity_id"], 2)

    def test_simple_contextual_result_reference_uses_saved_real_titles_locally(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            self.post("Find Explorer", "context_tab")
        with patch("main.interpret") as mocked:
            data = self.post("Open the second one", "context_tab").json()
        mocked.assert_not_called()
        self.assertEqual(data["action"]["event"]["title"], "Explorer Workshop")

    def test_show_details_uses_prior_selection(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            self.post("Find Explorer", "tab_details")
        with self.intent({"intent": "open_event", "result_index": 1}):
            self.post("Open first", "tab_details")
        with self.intent({"intent": "show_event_details"}):
            data = self.post("Show details", "tab_details").json()
        self.assertEqual(data["action"]["action"], "show_event_details")
        self.assertEqual(data["action"]["event"]["title"], "Explorer Night")

    def test_unambiguous_result_followup_skips_second_ai_request(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}) as mocked:
            search = self.post("Find Explorer events", "fast_followup").json()
            opened = self.post("Open the first result", "fast_followup")
        self.assertEqual(search["action"]["action"], "search_events")
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.json()["action"]["action"], "open_event")
        self.assertEqual(opened.json()["action"]["event"]["title"], "Explorer Night")
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("local_followup;dur=", opened.headers.get("server-timing", ""))

    def test_ambiguous_contextual_followup_asks_locally(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}) as mocked:
            self.post("Find Explorer events", "ambiguous_followup")
            result = self.post("Open that result", "ambiguous_followup")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["action"]["action"], "clarify")
        self.assertEqual(mocked.call_count, 1)

    def test_followup_without_results_asks_for_clarification(self):
        with self.intent({"intent": "show_event_details"}):
            data = self.post("Show details").json()
        self.assertEqual(data["action"]["action"], "clarify")

    def test_out_of_range_result_index_asks_for_clarification(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            self.post("Find Explorer", "tab_bad_index")
        with self.intent({"intent": "open_event", "result_index": 20}):
            data = self.post("Open result 20", "tab_bad_index").json()
        self.assertEqual(data["action"]["action"], "clarify")

    def test_sessions_do_not_share_results(self):
        with self.intent({"intent": "search_events", "query": "Explorer"}):
            self.post("Find Explorer", "tab_one")
        with self.intent({"intent": "open_event", "result_index": 1}):
            data = self.post("Open first", "tab_two").json()
        self.assertEqual(data["action"]["action"], "clarify")

    def test_show_more_advances_to_next_page(self):
        with self.intent({"intent": "search_events", "query": "events"}):
            # Common-word removal makes this a request for the available public event list.
            self.post("List events", "tab_more")
        with self.intent({"intent": "show_more_events"}):
            data = self.post("Show more", "tab_more").json()
        self.assertEqual(data["action"]["action"], "search_events")
        self.assertEqual(len(data["action"]["results"]), 1)
        self.assertFalse(data["action"]["has_more"])

    def test_malicious_extra_ai_url_is_rejected(self):
        with self.intent({"intent": "navigate", "route": "home", "url": "https://evil.invalid"}):
            response = self.post("go somewhere")
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("evil.invalid", response.text)

    def test_arbitrary_navigation_is_rejected_by_validator(self):
        with self.assertRaises(EchoError):
            validate_intent({"intent": "navigate", "route": "https://evil.invalid"})

    def test_navigation_supported_route(self):
        with self.intent({"intent": "navigate", "route": "contacts"}):
            data = self.post("Open contacts").json()
        self.assertEqual(data["action"], {"action": "navigate", "route": "contacts"})

    def test_navigation_supports_real_dashboard_sections(self):
        for route in ("campus", "map", "events", "announcements", "progress"):
            with self.subTest(route=route), self.intent({"intent": "navigate", "route": route}):
                data = self.post(f"Open {route}", f"tab_route_{route}").json()
            self.assertEqual(data["action"], {"action": "navigate", "route": route})

    def test_local_stop_does_not_call_ai(self):
        with self.intent({"intent": "answer", "text": "wrong"}) as mocked:
            data = self.post("Echo, stop talking").json()
            mocked.assert_not_called()
        self.assertEqual(data["action"]["action"], "stop_speaking")

    def test_conversation_mentioning_stop_phrase_is_not_intercepted(self):
        with self.intent({"intent": "answer", "text": "I can help with wording."}) as mocked:
            data = self.post("What does 'be quiet' mean in this story?").json()
        mocked.assert_called_once()
        self.assertEqual(data["action"]["action"], "answer")

    def test_model_output_with_sql_is_rejected(self):
        with self.assertRaises(EchoError):
            validate_intent({"intent": "search_events", "query": "x", "sql": "DROP TABLE activities"})

    def test_rate_limit_is_applied(self):
        main._echo_rate.clear()
        with self.intent({"intent": "answer", "text": "ok"}):
            for _ in range(20):
                response = self.post("hi", "rate_tab")
                self.assertEqual(response.status_code, 200)
            self.assertEqual(self.post("hi", "rate_tab").status_code, 429)


class AIWireTests(unittest.TestCase):
    class JsonResponse:
        headers = {"Content-Type": "application/json"}

        def __init__(self, content):
            self.raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit=None):
            return self.raw

    def test_plain_conversational_text_becomes_answer_without_action(self):
        with patch("echo_assistant.urlopen", return_value=self.JsonResponse("Yes, I can understand you. What would you like help with?")):
            with patch.dict(os.environ, {"FREELLMAPI_API_KEY": "unit-test-key",
                                         "FREELLMAPI_BASE_URL": "http://127.0.0.1:31415/v1",
                                         "FREELLMAPI_MODEL": "auto"}):
                result = interpret("Can you understand me?", [], [])
        self.assertEqual(result["intent"], "answer")
        self.assertIn("understand you", result["text"])

    def test_malformed_action_response_never_becomes_an_action(self):
        with patch("echo_assistant.urlopen", return_value=self.JsonResponse('{"intent":"navigate","route":"home"')):
            with patch.dict(os.environ, {"FREELLMAPI_API_KEY": "unit-test-key",
                                         "FREELLMAPI_BASE_URL": "http://127.0.0.1:31415/v1",
                                         "FREELLMAPI_MODEL": "auto"}):
                result = interpret("Show upcoming events", [], [])
        self.assertEqual(result["intent"], "clarify")
        self.assertNotIn("route", result)

    def test_openai_compatible_authenticated_request_and_json_parsing(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                raw = json.dumps({"choices": [{"message": {"content": '{"intent":"answer","text":"Hello from test"}'}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *_):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("echo_assistant.urlopen", wraps=echo_assistant.urlopen) as mocked_urlopen:
                with patch.dict(os.environ, {"FREELLMAPI_API_KEY": "unit-test-key",
                                             "FREELLMAPI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                                             "FREELLMAPI_MODEL": "auto"}):
                    history = [{"role": "user", "content": f"turn-{index}"} for index in range(10)]
                    result = interpret("hello", history, [])
            self.assertEqual(result["text"], "Hello from test")
            self.assertEqual(captured["path"], "/v1/chat/completions")
            self.assertEqual(captured["auth"], "Bearer unit-test-key")
            self.assertEqual(captured["body"]["model"], "auto")
            self.assertFalse(captured["body"]["stream"])
            self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
            self.assertEqual(captured["body"]["max_tokens"], 128)
            self.assertEqual(captured["body"]["messages"][1:7], history[-6:])
            self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 40)
        finally:
            server.shutdown()
            server.server_close()

    def test_missing_key_fails_without_network_request(self):
        with patch.dict(os.environ, {"FREELLMAPI_API_KEY": ""}):
            with self.assertRaises(MissingAIConfiguration):
                interpret("hello", [])

    def test_malformed_model_json_is_rejected(self):
        with self.assertRaises(EchoError):
            validate_intent({"intent": "answer", "text": ""})


class SessionStoreTests(unittest.TestCase):
    def test_ttl_expires_session(self):
        now = [0.0]
        store = SessionStore(ttl_seconds=30, clock=lambda: now[0])
        store.ensure("visitor_1")
        store.add_turn("visitor_1", "hi", "hello")
        now[0] = 31.0
        self.assertEqual(store.get("visitor_1")["history"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
