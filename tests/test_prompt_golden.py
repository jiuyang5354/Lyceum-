"""Prompt assembly contracts: byte-stable output, named sections, protected surface."""
import json
import pathlib
import unittest

from lyceum import agent, prompts

FIXTURE = pathlib.Path(__file__).with_name("fixtures") / "prompt-golden.json"
CASES = {
    "middle_math": ({"grade": 8, "textbook": "人教版"},
                    {"problem": "解方程 x^2-5x+6=0", "subject": "数学", "hint_level": 1, "stuck": 1}, False, None, "", None),
    "primary_unknown": ({"grade": 3, "textbook": "苏教版"}, {}, False, None, "", None),
    "high_full": ({"grade": 11, "textbook": "人教A版"},
                  {"problem": "求函数 f(x)=x^3-3x 的极值", "subject": "数学", "hint_level": 2, "stuck": 3}, True, None, "", None),
    "english_extras": ({"grade": 9, "textbook": "外研版"}, {"problem": "Translate: 他昨天去了图书馆", "subject": "英语"}, False, None,
                       "把这句话翻译成英语",
                       {"memories": [{"kind": "interest", "text": "喜欢篮球", "subject": "英语"}],
                        "prefs": {"depth": "brief"}, "thought": {"stuck_type": "表达"},
                        "arms": {"tactic": "visual_first", "pace": "patient"},
                        "lessons": ["表达卡点上「先画出来」效果好（3/3）"]}),
}


class PromptGoldenTest(unittest.TestCase):
    def test_rendered_prompt_is_byte_identical_to_the_recorded_contract(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for name, args in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(agent.system_prompt(*args), golden[name])

    def test_sections_cover_the_whole_prompt(self):
        args = CASES["middle_math"]
        built = agent.build_prompt(*args)
        self.assertEqual("".join(built.parts), built.text)
        self.assertEqual(built.text, agent.system_prompt(*args))
        self.assertEqual(list(built.sizes), list(prompts.ORDER))

    def test_protected_sections_are_declared_and_bounded(self):
        sections = prompts.SECTIONS
        self.assertEqual(set(prompts.PROTECTED), {"principles", "output", "state"})
        for name in prompts.PROTECTED:
            self.assertIn(name, sections)
            self.assertGreater(sections[name].budget, 0)

    def test_section_sizes_stay_within_budget(self):
        for name, spec in prompts.SECTIONS.items():
            with self.subTest(section=name):
                self.assertLessEqual(len(prompts.render_section(name, grade=8, subject="数学", band="middle")), spec.budget)

    def test_guard_fingerprint_ignores_teaching_variation_but_not_policy_edits(self):
        base = prompts.guard_fingerprint()
        a = prompts.guard_fingerprint(tactic="visual_first", pace="patient")
        self.assertEqual(base, a, "pedagogical variation must not change the guard fingerprint")
        original = prompts.SECTIONS["principles"].text
        try:
            prompts.SECTIONS["principles"].text = original + " 补充规则。"
            self.assertNotEqual(base, prompts.guard_fingerprint())
        finally:
            prompts.SECTIONS["principles"].text = original

    def test_stable_prefix_across_grades_and_subjects(self):
        first = agent.system_prompt({"grade": 3}, {"problem": "第一题", "subject": "数学"}, False)[:1200]
        second = agent.system_prompt({"grade": 11}, {"problem": "另一题", "subject": "物理"}, True)[:1200]
        self.assertEqual(first, second, "cacheable policy prefix must not vary with grade/subject")


if __name__ == "__main__":
    unittest.main()
