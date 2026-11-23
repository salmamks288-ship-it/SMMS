import time
from .base import Base

class TestRecommendationsAndChatbot(Base):
    def test_TC_FR_29_at_least_five_with_reasons_when_interests_given(self):
        v = self.visitor; self.patch("/api/me", v, {"interests": ["Archaeology", "Maritime"]})
        t0 = time.perf_counter(); r = self.get("/api/recommendations", v).get_json()
        self.assertLess(time.perf_counter() - t0, 3.0)                                     # NFR-04
        self.assertEqual(r["mode"], "personalised"); self.assertGreaterEqual(len(r["items"]), 5)
        self.assertTrue(all(i["reason"] for i in r["items"]))
        top = [i["category"] for i in r["items"][:2]]; self.assertTrue(set(top) <= {"Archaeology", "Maritime"})
        self.assertTrue(all(i["gallery_location"] for i in r["items"]))                    # FR-30

    def test_TC_FR_29_no_data_shows_popular_exhibits(self):
        r = self.get("/api/recommendations", self.visitor).get_json()                       # demo visitor has no interests/history
        self.assertIn("popular", r["mode"]); self.assertGreaterEqual(len(r["items"]), 5)

    def test_TC_FR_07_NL3_no_personal_data_used_after_consent_withdrawn(self):
        v = self.visitor; self.patch("/api/me", v, {"interests": ["Textiles"]})
        before = len(self.sql("SELECT 1 FROM recommendation"))
        self.patch("/api/me", v, {"consent_personalisation": False})
        r = self.get("/api/recommendations", v).get_json()
        self.assertIn("consent", r["mode"]); self.assertEqual(len(self.sql("SELECT 1 FROM recommendation")), before)   # nothing stored

    def test_TC_FR_28_rating_dismiss_and_exclusion(self):
        v = self.visitor; self.patch("/api/me", v, {"interests": ["Art"]})
        first = self.get("/api/recommendations", v).get_json()["items"][0]
        self.assertEqual(self.post("/api/feedback", v, {"artifact_id": first["artifact_id"], "rating": 6}).status_code, 400)
        self.assertEqual(self.post("/api/feedback", v, {"artifact_id": first["artifact_id"], "rating": 5}).status_code, 201)
        self.post("/api/feedback", v, {"artifact_id": first["artifact_id"], "rating": 4})  # update, not duplicate
        self.assertEqual(len(self.sql("SELECT 1 FROM feedback")), 1)
        self.assertEqual(self.post(f"/api/recommendations/{first['artifact_id']}/action", v, {"action": "dismiss"}).status_code, 200)
        ids = [i["artifact_id"] for i in self.get("/api/recommendations", v).get_json()["items"]]
        self.assertNotIn(first["artifact_id"], ids)

    def test_TC_NFR_32_20_personas_no_exhibit_in_more_than_40_percent_of_top_five_lists(self):
        """20 personas with different interests over a 48-exhibit catalogue; personas with different interests get different lists."""
        import random
        from collections import Counter
        random.seed(4); s = self.staff
        words = {"Archaeology": "bronze pottery burial tomb excavation ancient tool seal ring mask", "Textiles": "wool silk weaving embroidery garment dye loom thread carpet veil",
                 "Maritime": "dhow pearl diving anchor rope trade sail harbour fishing compass", "Art": "painting calligraphy gold ink landscape portrait sculpture canvas frame brush"}
        cat = {"Archaeology": 1, "Textiles": 2, "Maritime": 3, "Art": 4}
        for i in range(40):
            c = random.choice(list(words)); d = " ".join(random.sample(words[c].split(), 4)) + " museum object"
            self.post("/api/artifacts", s, {"title": f"{c} item {i}", "category_id": cat[c], "description": d, "period": "1900", "origin": "UAE", "condition": "good", "location": "G1", "status": "onDisplay"})
        cnt, lists = Counter(), {}
        for i in range(20):
            tok = self.new_visitor(f"q{i}@example.com"); ints = random.sample(list(words), random.choice([1, 2, 3]))
            self.patch("/api/me", tok, {"interests": ints})
            top = [it["artifact_id"] for it in self.get("/api/recommendations", tok).get_json()["items"][:5]]
            cnt.update(top); lists[tuple(sorted(ints))] = lists.get(tuple(sorted(ints)), []) + [tuple(top)]
        self.assertLessEqual(max(cnt.values()) / 20, 0.40)
        different = [v[0] for v in lists.values()]
        self.assertGreater(len(set(different)), 1)

    def test_personas_with_different_interests_get_different_leading_exhibits(self):
        lead = {}
        for i, interest in enumerate(["Archaeology", "Textiles", "Maritime", "Art"]):
            tok = self.new_visitor(f"p{i}@example.com"); self.patch("/api/me", tok, {"interests": [interest]})
            lead[interest] = self.get("/api/recommendations", tok).get_json()["items"][0]["category"]
        self.assertEqual(lead, {k: k for k in lead})

    def test_TC_FR_27_exhibit_page_by_scanned_code(self):
        v = self.visitor; r = self.get("/api/exhibits/by-code/ART-DEMO00", v).get_json()
        self.assertEqual(r["title"], "Bronze Age Mask"); self.assertTrue(r["ar_enabled"]); self.assertTrue(r["related"])

    def test_TC_FR_31_chatbot_answers_from_knowledge_base_with_source(self):
        v = self.visitor
        r = self.post("/api/chat", v, {"question": "Is the museum wheelchair accessible?", "language": "EN"}).get_json()
        self.assertFalse(r["fallback"]); self.assertIn("step free", r["answer"]); self.assertIn("Accessibility", r["source"])
        r = self.post("/api/chat", v, {"question": "What time do you open?", "language": "EN"}).get_json()
        self.assertIn("10:00", r["answer"])

    def test_TC_FR_32_fallback_logs_question_and_shows_helpdesk(self):
        v = self.visitor
        r = self.post("/api/chat", v, {"question": "Do you sell quantum computers?", "language": "EN"}).get_json()
        self.assertTrue(r["fallback"]); self.assertIn("Help desk", r["answer"])
        self.assertEqual(self.get("/api/kb/unanswered", self.staff).get_json()[0]["question"], "Do you sell quantum computers?")

    def test_TC_NFR_31_out_of_scope_questions_use_fallback(self):
        v = self.visitor
        oos = ["Who won the football match yesterday?", "Can you give me a pasta recipe?", "What is the capital of Mongolia?",
               "How do I fix my washing machine?", "Tell me about stock market prices", "Where can I buy a car?"]
        fb = sum(self.post("/api/chat", v, {"question": q, "language": "EN"}).get_json()["fallback"] for q in oos)
        self.assertGreaterEqual(fb / len(oos), 0.9)                                         # NFR-31: >= 90% fallback

    def test_TC_NFR_31_in_scope_accuracy_at_least_85_percent(self):
        v = self.visitor
        cases = [("When does the museum open?", "10:00"), ("What are your opening hours", "10:00"), ("Is there wheelchair access?", "step free"),
                 ("How much is an adult ticket?", "30 AED"), ("What does a ticket cost?", "30 AED"), ("Can I take photos in the galleries?", "Photography"),
                 ("Are cameras allowed", "Photography"), ("student ticket price", "20 AED")]
        ok = sum(exp in self.post("/api/chat", v, {"question": q, "language": "EN"}).get_json()["answer"] for q, exp in cases)
        self.assertGreaterEqual(ok / len(cases), 0.85)

    def test_TC_FR_33_only_published_entries_are_used(self):
        s, v = self.staff, self.visitor
        eid = self.post("/api/kb/entries", s, {"question": "Is there a rooftop cafe?", "answer": "Yes the rooftop cafe opens at 9.", "language": "EN"}).get_json()["entry_id"]
        self.assertTrue(self.post("/api/chat", v, {"question": "rooftop cafe?", "language": "EN"}).get_json()["fallback"])      # draft is not used
        self.patch(f"/api/kb/entries/{eid}", s, {"status": "published"})
        self.assertFalse(self.post("/api/chat", v, {"question": "rooftop cafe?", "language": "EN"}).get_json()["fallback"])
        self.patch(f"/api/kb/entries/{eid}", s, {"status": "unpublished"})
        self.assertTrue(self.post("/api/chat", v, {"question": "rooftop cafe?", "language": "EN"}).get_json()["fallback"])

    def test_TC_FR_31_arabic_questions_use_arabic_entries(self):
        s, v = self.staff, self.visitor
        eid = self.post("/api/kb/entries", s, {"question": "ما هي ساعات العمل؟", "answer": "المتحف مفتوح من ١٠ صباحا حتى ٦ مساء", "language": "AR"}).get_json()["entry_id"]
        self.patch(f"/api/kb/entries/{eid}", s, {"status": "published"})
        r = self.post("/api/chat", v, {"question": "ما هي ساعات العمل", "language": "AR"}).get_json()
        self.assertFalse(r["fallback"]); self.assertIn("مفتوح", r["answer"])

class TestAR(Base):
    def test_TC_FR_34_launch_returns_model_and_overlay(self):
        r = self.get("/api/ar/1", self.visitor).get_json(); self.assertTrue(r["ar"]); self.assertTrue(r["model_url"])
    def test_TC_FR_35_fallback_when_unsupported_or_permission_refused(self):
        v = self.visitor
        for qs in ("?supports_ar=0", "?camera_permission=0"):
            r = self.get("/api/ar/1" + qs, v).get_json(); self.assertFalse(r["ar"]); self.assertTrue(r["fallback"]["text"])
        self.assertFalse(self.get("/api/ar/2", v).get_json()["ar"])                          # exhibit without AR content
    def test_TC_FR_36_ar_content_limit_20mb_and_publish_toggle(self):
        s = self.staff
        self.assertEqual(self.post("/api/ar-content", s, {"artifact_id": 2, "model_url": "/m.glb", "file_size_mb": 25}).status_code, 400)   # NFR-05
        cid = self.post("/api/ar-content", s, {"artifact_id": 2, "model_url": "/m.glb", "file_size_mb": 12, "overlay_text": "x"}).get_json()["content_id"]
        self.assertFalse(self.get("/api/ar/2", self.visitor).get_json()["ar"])               # unpublished
        self.patch(f"/api/ar-content/{cid}", s, {"published": 1}); self.assertTrue(self.get("/api/ar/2", self.visitor).get_json()["ar"])
    def test_TC_FR_41_ar_session_is_anonymous(self):
        v = self.visitor; self.assertEqual(self.post("/api/ar/sessions", v, {"content_id": 1, "duration_seconds": 40, "device_type": "Android"}).status_code, 201)
        self.assertNotIn("visitor_id", [c["name"] for c in self.sql("PRAGMA table_info(ar_session)")])
