"""Offline token/call regressions. Model responses are fixtures, not live evaluations."""
import copy
import json
import unittest
from unittest.mock import patch

from lyceum import agent, llm


class GradeEfficiencyTest(unittest.TestCase):
    def test_fully_verifiable_batch_never_calls_model(self):
        questions = [
            {"q": "计算 1/2+1/3", "answer": "5/6"},
            {"q": "解方程 2x+3=11", "answer": "x=4"},
        ]
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", return_value={}) as call:
            result = agent.grade_answers({"grade": 8}, {}, questions, ["5/6", "x=3"])
        call.assert_not_called()
        self.assertEqual([r["correct"] for r in result], [True, False])
        self.assertTrue(all(r["checked"] for r in result))

    def test_only_unknown_items_enter_single_model_call(self):
        questions = [{"q": "计算 1/2+1/3", "answer": "5/6"},
                     {"q": "《静夜思》作者", "answer": "李白"},
                     {"q": "解方程 2x+3=11", "answer": "x=4"}]
        before = copy.deepcopy(questions)
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", return_value={
            "results": [{"correct": True, "feedback": "作者判断正确。"}]
        }) as call:
            result = agent.grade_answers({"grade": 8}, {}, questions, ["5/6", "李白", "x=3"])
        call.assert_called_once()
        prompt = call.call_args.args[0][0]["content"]
        self.assertNotIn("1/2+1/3", prompt)
        self.assertNotIn("2x+3=11", prompt)
        self.assertIn("静夜思", prompt)
        self.assertEqual([r["correct"] for r in result], [True, True, False])
        self.assertEqual([r["checked"] for r in result], [True, False, True])
        self.assertEqual(questions, before)


    def test_incomplete_or_non_boolean_grading_is_not_false_evidence(self):
        for response in ({}, {"results": [{"correct": "false", "feedback": "bad type"}]},
                         {"results": [{"correct": True}, {"correct": False}]}):
            with self.subTest(response=response), patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", return_value=response):
                with self.assertRaises(llm.LLMError):
                    agent.grade_answers({"grade": 8}, {}, [{"q": "《静夜思》作者", "answer": "李白"}], ["李白"])

    def test_missing_answer_is_blank_and_empty_batch_is_free(self):
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat") as call:
            result = agent.grade_answers({"grade": 8}, {}, [{"q": "计算1+1", "answer": "2"}], [])
            self.assertEqual(result[0]["correct"], False)
            self.assertEqual(agent.grade_answers({}, {}, [], []), [])
        call.assert_not_called()


class ContextEfficiencyTest(unittest.TestCase):
    def test_known_subject_loads_only_its_taxonomy(self):
        prompt = agent.system_prompt({"grade": 8}, {"subject": "数学"}, False)
        self.assertIn("因式分解", prompt)
        self.assertIn("- 数学：", prompt)
        self.assertNotIn("- 历史：", prompt)
        self.assertIn("第 1、2 层", prompt)  # Never remove pedagogy to meet a budget.
        self.assertIn("12355", prompt)
        unknown = agent.system_prompt({"grade": 8}, {}, False)
        self.assertIn("- 历史：", unknown)
    def test_history_budget_keeps_recent_exchanges_verbatim(self):
        history = []
        for i in range(7):
            history.extend([{"role": "user", "content": f"第{i}次：x=2/3"},
                            {"role": "assistant", "content": ("旧解释。" * 400) if i < 5 else f"最近追问{i}"}])
        before = copy.deepcopy(history)
        selected = agent.history_messages(history)
        self.assertLessEqual(sum(len(m["content"]) for m in selected), 6000)
        self.assertEqual(selected[-4:], history[-4:])
        self.assertEqual(selected[0]["role"], "user")
        self.assertEqual(history, before)

    def test_recent_long_student_work_is_not_truncated(self):
        work = "我的证明与原始条件：x=-2/3。" * 600
        selected = agent.history_messages([{"role": "user", "content": work},
                                            {"role": "assistant", "content": "下一步呢？"}])
        self.assertEqual(selected[0]["content"], work)


    def test_policy_prefix_is_stable_across_students_and_turns(self):
        a = agent.system_prompt({"grade": 3}, {"problem": "第一题", "subject": "数学"}, False)
        b = agent.system_prompt({"grade": 11}, {"problem": "另一题", "subject": "物理"}, True)
        self.assertTrue(a[:1200] == b[:1200])
        self.assertIn("续题未改题干时填空字符串", a)


class GateAuthorizationTest(unittest.TestCase):
    ST = {"problem": "解方程 x^2-5x+6=0", "subject": "数学", "hint_level": 1, "stuck": 0}

    def test_model_stage_cannot_authorize_answers_in_sync_or_stream(self):
        for stage in ("full", "redirect"):
            for streaming in (False, True):
                with self.subTest(stage=stage, streaming=streaming):
                    draft = {"subject": "数学", "intent": "ask_hint", "stage": stage,
                             "hint_level": 1, "solved": True, "reply": "答案是 x=2 或 x=3。"}
                    events = []
                    with patch.object(llm, "enabled", return_value=True), \
                         patch.object(llm, "chat", side_effect=lambda *a, **k: dict(draft)), \
                         patch.object(llm, "chat_stream", return_value=iter([json.dumps(draft, ensure_ascii=False)])):
                        if streaming:
                            out, state = agent.respond_stream({"grade": 8}, {"state": dict(self.ST)}, [], "再提示一点",
                                                              emit=lambda e, d: events.append((e, d)))
                        else:
                            out, state = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "再提示一点")
                    self.assertFalse(out["allow_full"])
                    self.assertFalse("答案是" in out["reply"])
                    self.assertFalse(any("答案是" in d.get("text", "") for e, d in events))
                    self.assertFalse(state.get("full_given", False))
                    self.assertFalse(state.get("solved", False))

    def test_server_authorized_full_solution_still_works(self):
        draft = {"subject": "数学", "intent": "ask_full", "stage": "full", "hint_level": 1,
                 "solved": True, "reply": "答案是 x=2 或 x=3。"}
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", return_value=draft):
            out, state = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "", action="full")
        self.assertTrue(out["allow_full"])
        self.assertTrue(state["full_given"])
        self.assertEqual(out["reply"], draft["reply"])


class RepairEfficiencyTest(unittest.TestCase):
    def test_repair_preserves_previous_work_and_two_complete_exchanges(self):
        from lyceum.context import repair_messages
        system = {"role": "system", "content": "保留教学和安全规则；题目 x^2-5x+6=0。"}
        older = [{"role": "user", "content": "更早的问题"},
                 {"role": "assistant", "content": "更早的解释"}]
        recent = [{"role": "user", "content": "我先移项得到 x^2-5x=-6。"},
                  {"role": "assistant", "content": "请继续写出你的过程。"},
                  {"role": "user", "content": "我的过程是 x(x-5)=-6，所以 x=6。"},
                  {"role": "assistant", "content": "检查由乘积推断 x 的那一步。"}]
        draft = "因式分解是 (x-2)(x-3)=0。"
        instruction = {"role": "user", "content": "修正泄题，依据学生原过程给提示。"}
        for content in ("刚才那一步哪里错了？", [
                {"type": "text", "text": "刚才那一步哪里错了？"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}]):
            with self.subTest(multimodal=isinstance(content, list)):
                current = {"role": "user", "content": content}
                messages = [system, *older, *recent, current]
                before = copy.deepcopy(messages)
                repaired = repair_messages(messages, draft, instruction)
                self.assertEqual(repaired, [system, *recent, current,
                                          {"role": "assistant", "content": draft}, instruction])
                self.assertEqual(messages, before)

    def test_leak_and_verdict_share_one_repair_budget(self):
        history = [{"role": r, "content": f"第{i}轮{r}：" + "教学讨论。" * 40}
                   for i in range(3) for r in ("user", "assistant")]
        bad = {"subject": "数学", "intent": "answer_attempt", "stage": "check", "hint_level": 1,
               "student_correct": True, "solved": True, "reply": "因式分解是 (x-2)(x-3)=0。"}
        still_wrong = dict(bad, reply="完全正确！")
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", side_effect=[bad, still_wrong, still_wrong]) as call:
            out, _ = agent.respond({"grade": 8}, {"state": dict(GateAuthorizationTest.ST)}, history, "x=1 或 x=6")
        self.assertEqual(call.call_count, 2)
        self.assertFalse(out["student_correct"])
        self.assertEqual(out["reply"], agent.VERIFY_WRONG)
        first, repair = [x.args[0] for x in call.call_args_list]
        self.assertEqual(repair[0], first[0])
        self.assertEqual(repair[1:-3], history[-4:])
        self.assertEqual(repair[-3], first[-1])
        self.assertEqual(repair[-2], {"role": "assistant", "content": bad["reply"]})
        for omitted in history[:-4]:
            self.assertNotIn(omitted, repair)


class InterruptedUsageTest(unittest.TestCase):
    def test_usage_before_abnormal_eof_is_measured_and_accounted_once(self):
        import io
        usage: dict = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"partial"}}],'
            b'"usage":{"prompt_tokens":12,"completion_tokens":3}}\n')
        with patch.object(llm, "USAGE", usage), patch.object(llm, "USAGE_FILE", None):
            stream = llm._read_stream(response, {"model": "fixture"}, [{"role": "user", "content": "x"}])
            self.assertEqual(next(stream), "partial")
            with self.assertRaises(llm.LLMError):
                list(stream)
            stream.close()  # Closing after the exception must not count twice.
            self.assertEqual(usage["calls"], 1)
            self.assertEqual(usage["prompt_tokens"], 12)
            self.assertEqual(usage["completion_tokens"], 3)
            model = usage["by_model"]["fixture"]
            self.assertEqual(model["calls"], 1)
            self.assertEqual(model["prompt_tokens"], 12)
            self.assertEqual(model["completion_tokens"], 3)
            self.assertEqual(model["interrupted_calls"], 1)
            self.assertFalse(model["estimated"])
            self.assertEqual(model["estimated_calls"], 0)

    def test_partial_stream_is_accounted_once_on_disconnect_and_close(self):
        import io
        for close_early in (False, True):
            usage: dict = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
            with self.subTest(close=close_early), patch.object(llm, "USAGE", usage), patch.object(llm, "USAGE_FILE", None):
                response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n')
                stream = llm._read_stream(response, {"model": "fixture"}, [{"role": "user", "content": "x"}])
                self.assertEqual(next(stream), "hello")
                if close_early:
                    stream.close()
                else:
                    with self.assertRaises(llm.LLMError):
                        list(stream)
                self.assertEqual(usage["calls"], 1)
                self.assertEqual(usage["by_model"]["fixture"]["calls"], 1)
                self.assertEqual(usage["by_model"]["fixture"]["interrupted_calls"], 1)


if __name__ == "__main__":
    unittest.main()
