"""Client accounting/negotiation; fake transports only, no model calls."""
import io
from email.message import Message
import json
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from lyceum import llm


def stream(*events, done=True):
    body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
    return io.BytesIO(body + (b"data: [DONE]\n\n" if done else b""))


def bad(message):
    return urllib.error.HTTPError("http://fake", 400, "Bad Request", Message(), io.BytesIO(message.encode()))


class EfficiencyTest(unittest.TestCase):
    def test_zero_usage_is_measured(self):
        for streaming in (True, False):
            with self.subTest(streaming=streaming):
                usage = {"prompt_tokens": 0, "completion_tokens": 0}
                if streaming:
                    with patch.object(llm, "_open_stream", return_value=stream({"usage": usage})):
                        list(llm.chat_stream([], json_mode=False))
                else:
                    with patch.object(llm, "_post", return_value={"choices": [{"message": {"content": ""}}], "usage": usage}):
                        llm._chat_one("model-a", [], False, .4, 10, 0)
                r = llm.USAGE["by_model"]["model-a"]
                self.assertEqual((r["prompt_tokens"], r["completion_tokens"], r["estimated"]), (0, 0, False))

    def test_missing_usage_is_auditable(self):
        with patch.object(llm, "_post", return_value={"choices": [{"message": {"content": "hello"}}]}):
            llm._chat_one("model-a", [], False, .4, 10, 0)
        self.assertEqual(llm.USAGE["by_model"]["model-a"].get("estimated_calls"), 1)

    def test_response_format_memory_shared_with_stream(self):
        sent = []
        def post(payload):
            sent.append(dict(payload))
            if len(sent) == 1:
                raise bad("response_format is not supported")
            return {"choices": [{"message": {"content": "{}"}}]}
        with patch.object(llm, "_post", side_effect=post):
            for _ in range(2):
                llm._chat_one("model-a", [], True, .4, 10, 0)
        def open_(payload):
            sent.append(dict(payload))
            return stream()
        with patch.object(llm, "_open_stream", side_effect=open_):
            list(llm.chat_stream([]))
        self.assertEqual(len(sent), 4)
        self.assertIn("response_format", sent[0])
        for payload in sent[1:]:
            self.assertNotIn("response_format", payload)

    def test_usage_cumulative_zero_cached_and_estimation_audit(self):
        messages = [{"role": "user", "content": "hello world"}]
        with tempfile.TemporaryDirectory() as directory, patch.object(llm, "USAGE_FILE", directory + "/usage.json"):
            with patch.object(llm, "_open_stream", return_value=stream(
                    {"usage": {"prompt_tokens": 10, "completion_tokens": 1}},
                    {"usage": {"prompt_tokens": 10, "completion_tokens": 4,
                               "prompt_tokens_details": {"cached_tokens": 6}}},
                    {"usage": {"prompt_tokens": 10, "completion_tokens": 4,
                               "prompt_tokens_details": {"cached_tokens": 6}}})):
                list(llm.chat_stream(messages, json_mode=False))
            self.assertEqual((llm.USAGE["prompt_tokens"], llm.USAGE["completion_tokens"], llm.USAGE["cached_tokens"]), (10, 4, 6))
            for streaming in (True, False):
                usage = {"prompt_tokens": 0, "completion_tokens": 0}
                if streaming:
                    with patch.object(llm, "_open_stream", return_value=stream({"usage": usage})):
                        list(llm.chat_stream(messages, json_mode=False))
                else:
                    with patch.object(llm, "_post", return_value={"choices": [{"message": {"content": ""}}], "usage": usage}):
                        llm._chat_one("model-a", messages, False, .4, 10, 0)
            record = llm.USAGE["by_model"]["model-a"]
            self.assertEqual((record["calls"], record["prompt_tokens"], record["completion_tokens"]), (3, 10, 4))
            self.assertEqual(record["estimated_calls"], 0)
            for streaming in (True, False):
                if streaming:
                    with patch.object(llm, "_open_stream", return_value=stream()):
                        list(llm.chat_stream(messages, json_mode=False))
                else:
                    with patch.object(llm, "_post", return_value={"choices": [{"message": {"content": ""}}]}):
                        llm._chat_one("model-a", messages, False, .4, 10, 0)
            self.assertEqual(record["estimated_calls"], 2)
            self.assertEqual(record["cached_tokens"], 6)
            self.assertEqual(llm.USAGE["estimated_calls"], 2)
            self.assertEqual(llm.usage_totals()["model-a"], record)

    def setUp(self):
        for name, value in {"BASE_URL": "http://efficiency.invalid/" + self.id(), "USAGE_FILE": None,
                            "USAGE": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}}.items():
            p = patch.object(llm, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(llm, "candidates", return_value=["model-a"])
        p.start()
        self.addCleanup(p.stop)

    def test_stream_option_negotiated_once_and_scoped(self):
        sent = []
        def open_(payload):
            sent.append(dict(payload))
            if len(sent) == 1:
                raise bad("Unsupported parameter: stream_options.include_usage")
            return stream()
        with patch.object(llm, "_open_stream", side_effect=open_):
            for _ in range(2):
                list(llm.chat_stream([], json_mode=False))
            with patch.object(llm, "candidates", return_value=["model-b"]):
                list(llm.chat_stream([], json_mode=False))
            with patch.object(llm, "BASE_URL", "http://other.invalid"):
                list(llm.chat_stream([], json_mode=False))
        self.assertEqual(len(sent), 5)
        self.assertEqual(sent[0]["stream_options"], {"include_usage": True})
        self.assertNotIn("stream_options", sent[1])
        self.assertNotIn("stream_options", sent[2])
        self.assertIn("stream_options", sent[3])
        self.assertIn("stream_options", sent[4])

    def test_unrelated_400_not_retried(self):
        for streaming in (True, False):
            with self.subTest(streaming=streaming):
                transport = "_open_stream" if streaming else "_post"
                with patch.object(llm, transport, side_effect=lambda p: (_ for _ in ()).throw(bad("Invalid messages"))) as op:
                    with self.assertRaisesRegex(llm.LLMError, "Invalid messages"):
                        if streaming:
                            list(llm.chat_stream([]))
                        else:
                            llm._chat_one("model-a", [], True, .4, 10, 1)
                self.assertEqual(op.call_count, 1)

    def test_partial_stream_never_falls_back(self):
        with patch.object(llm, "candidates", return_value=["model-a", "model-b"]), patch.object(
                llm, "_open_stream", return_value=stream({"choices": [{"delta": {"content": "partial"}}]}, done=False)) as op:
            output = llm.chat_stream([])
            self.assertEqual(next(output), "partial")
            with self.assertRaises(llm.LLMError):
                next(output)
            self.assertEqual(op.call_count, 1)
