"""题库与在线难度标定的测试：答案必须能被 params 复算，推荐必须可解释。"""
import math
import os
import sys
import tempfile
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import itembank as B  # noqa: E402
from lyceum.db import DB  # noqa: E402


def recompute(it):
    """用 params 独立算一遍答案——题库的「第二意见」。"""
    p, kind = it["params"], it["params"]["kind"]
    if kind == "mul":
        return Fraction(p["a"] * p["b"])
    if kind == "add":
        return Fraction(p["a"] + p["b"])
    if kind == "perimeter":
        return Fraction(2 * (p["w"] + p["h"]))
    if kind == "linear":
        return Fraction(p["c"] - p["b"], p["a"])
    if kind == "system2":
        return Fraction(p["x"])
    if kind == "factor":
        return Fraction(min(p["p"], p["q"]))
    if kind == "quadratic":
        return Fraction(max(p["p"], p["q"]))
    if kind == "expand":
        return Fraction(p["a"] * p["d"] + p["b"] * p["c"])
    if kind == "pythagoras":
        return Fraction(round((p["a"] ** 2 + p["b"] ** 2) ** 0.5))
    if kind == "fracadd":
        return Fraction(p["a"] + p["b"], p["den"])
    if kind == "discount":
        return Fraction(p["price"] * (100 - p["off"]), 100)
    if kind == "triarea":
        return Fraction(p["w"] * p["h"], 2)
    if kind == "ap":
        return Fraction(p["a1"] + (p["n"] - 1) * p["d"])
    if kind == "gp":
        return Fraction(p["a1"] * p["q"] ** (p["n"] - 1))
    if kind == "dice":
        return Fraction(p["ways"], 36)
    if kind == "ohm":
        return Fraction(str(round(p["r"] * p["i"], 2)))
    if kind == "power":
        return Fraction(str(round(p["u"] * p["i"], 2)))
    if kind == "density":
        return Fraction(str(round(p["m"] / p["v"], 2)))
    if kind == "pressure":
        return Fraction(str(round(p["f"] / p["s"], 2)))
    if kind == "molarmass":
        return Fraction(sum(p["atoms"].values()))
    if kind == "amount":
        return Fraction(str(round(p["m"] / p["M"], 3)))
    if kind == "ineq":
        return Fraction((p["c"] - p["b"] - 1) // p["a"])
    if kind == "negops":
        return Fraction(-p["a"] + p["b"] * p["c"])
    if kind == "fracval":
        return Fraction(p["a"] * p["x"] + p["b"], p["x"])
    if kind == "sqrt":
        return Fraction(p["a"] * p["b"])
    if kind == "real":
        return Fraction(p["a"] + int(p["b"] ** 0.5))
    if kind == "linear_fn":
        return Fraction(p["k"] * p["x"] + p["b"])
    if kind == "inv_fn":
        return Fraction(p["k"], p["x"])
    if kind == "quad_fn":
        return Fraction(p["a"] * (p["x"] - p["h"]) ** 2 + p["k"])
    if kind == "similar":
        return Fraction(p["b"] * p["scale"])
    if kind == "trig":
        return Fraction(p["opp"], p["hyp"])
    if kind == "circum":
        return Fraction(str(round(2 * 3.14 * p["r"], 2)))
    if kind == "bag":
        return Fraction(p["red"], p["red"] + p["blue"])
    if kind == "mean":
        return Fraction(str(round(sum(p["vals"]) / len(p["vals"]), 2)))
    if kind == "speed":
        return Fraction(str(round(p["s"] / p["t"], 2)))
    if kind == "buoyancy":
        return Fraction(str(round(1000 * 10 * float(p["v"]), 2)))
    if kind == "work":
        return Fraction(p["f"] * p["s"])
    if kind == "heat":
        return Fraction(p["c"] * p["m"] * p["dt"])
    if kind == "massfrac":
        return Fraction(str(round(p["solute"] / p["total"] * 100, 1)))
    if kind == "eqcalc":
        return Fraction(p["h2"] * 9)
    if kind == "convert":
        return Fraction(int(p["m"] * 100))
    if kind == "ratio":
        return Fraction(p["a"] + p["k"])
    if kind == "boxvol":
        return Fraction(p["w"] * p["h"] * p["d"])
    if kind == "cylvol":
        return Fraction(str(round(3.14 * p["r"] * p["r"] * p["h"], 2)))
    if kind == "chicken":
        return Fraction(p["rabbits"])
    if kind == "trees":
        return Fraction(p["length"] // p["gap"] + 1)
    if kind == "travel":
        return Fraction(str(round(p["s"] / (p["v1"] + p["v2"]), 2)))
    if kind == "subset":
        return Fraction(2 ** p["n"] - 1)
    if kind == "complex_add":
        return Fraction(p["a"] + p["b"])
    if kind == "lever":
        return Fraction(str(round(p["f2"] * p["l2"] / p["l1"], 2)))
    if kind == "sound":
        return Fraction(p["v"] * p["t"])
    if kind == "kwh":
        return Fraction(str(round(p["p"] * p["t"] / 1000, 2)))
    if kind == "divq":
        return Fraction(p["q"])
    if kind == "area_rect":
        return Fraction(p["w"] * p["h"])
    if kind == "unit_len":
        return Fraction(p["m"] * 100)
    if kind == "avg3":
        return Fraction(sum(p["vals"]), 3)
    if kind == "time_min":
        return Fraction(p["h"] * 60)
    if kind == "change":
        return Fraction(p["pay"] - p["price"])
    if kind == "trip_p":
        return Fraction(p["v"] * p["t"])
    if kind == "sqdiff_const":
        return Fraction(-p["a"] * p["a"])
    if kind == "perfect_linear":
        return Fraction(2 * p["a"])
    if kind == "scinot":
        return Fraction(int(Fraction(str(p["c"])) * 10 ** p["n"]))
    if kind == "median5":
        return Fraction(sorted(p["vals"])[2])
    if kind == "log":
        return Fraction(p["k"])
    if kind == "exp_eq":
        return Fraction(p["k"])
    if kind == "trig_special":
        return {"sin 30°": Fraction(1, 2), "cos 60°": Fraction(1, 2),
                "tan 45°": Fraction(1), "sin 90°": Fraction(1)}[p["name"]]
    if kind in ("comb", "binom"):
        return Fraction(math.comb(p["n"], p["k"]))
    if kind == "series_r":
        return Fraction(p["r1"] + p["r2"])
    if kind == "parallel_r":
        return Fraction(p["r1"] * p["r2"], p["r1"] + p["r2"])
    if kind == "eff":
        return Fraction(p["useful"] * 100 // p["total"])
    if kind == "accel_disp":
        return Fraction(p["a"] * p["t"] * p["t"], 2)
    if kind == "kinetic":
        return Fraction(p["m"] * p["v"] * p["v"], 2)
    if kind == "momentum":
        return Fraction(p["m"] * p["v"])
    if kind == "conserve":
        return Fraction(p["ma"] + p["mb"])
    if kind == "atoms_count":
        return Fraction(p["n"])
    if kind == "molar_vol":
        return Fraction(str(round(float(p["n"]) * 22.4, 1)))
    if kind == "ph":
        return Fraction(p["k"])
    if kind == "gene":
        return Fraction(3, 4) if p["which"] == "显性性状" else Fraction(1, 4)
    if kind == "microscope":
        return Fraction(p["eye"] * p["obj"])
    if kind == "energy":
        return Fraction(p["base"] // 10)
    if kind == "cell_split":
        return Fraction(2 ** p["n"])
    if kind == "breath":
        return Fraction(p["rate"] * p["min"])
    if kind == "heart":
        return Fraction(p["hr"] * p["min"])
    if kind == "scale":
        return Fraction(p["cm"] * p["den"] // 100000)
    if kind == "density_pop":
        return Fraction(p["pop"] // p["area"])
    if kind == "lapse":
        return Fraction(str(round(0.6 * p["h"], 1)))
    if kind == "tz":
        return Fraction(p["diff"])
    if kind == "sun_alt":
        return Fraction(90 - abs(p["lat"] - p["decl"]))
    if kind == "contour":
        return Fraction(p["step"] * p["n"])
    if kind == "annual_range":
        return Fraction(p["hi"] - p["lo"])
    if kind in ("dictation", "idiom", "verb_past", "plural"):
        return p.get("next") or p.get("idiom") or p.get("past") or p.get("plural")
    raise AssertionError("未知模板 " + kind)


class BankTest(unittest.TestCase):
    def test_every_answer_recomputes_from_its_params(self):
        for it in B.ITEMS:
            want = recompute(it)
            if isinstance(want, str):
                self.assertEqual(want, it["answer"], it["id"] + " " + it["stem"])
            else:
                self.assertEqual(Fraction(it["answer"]), want, it["id"] + " " + it["stem"])

    def test_bank_is_big_enough_and_covers_several_topics(self):
        self.assertGreaterEqual(len(B.ITEMS), 530)
        self.assertGreaterEqual(len(B.topics()), 80)
        self.assertEqual({s for s, _ in B.topics()},
                         {"数学", "物理", "化学", "生物", "地理", "语文", "英语"})

    def test_every_topic_has_at_least_two_items_to_choose_from(self):
        from collections import Counter
        counts = Counter((it["subject"], it["topic"]) for it in B.ITEMS)
        thin = {k: v for k, v in counts.items() if v < 2}
        self.assertEqual(thin, {}, "每个知识点至少要能换一道题：%s" % thin)

    def test_every_subject_band_has_a_real_pool(self):
        from collections import Counter
        pools = Counter((it["subject"], it["band"]) for it in B.ITEMS)
        for key, n in pools.items():
            self.assertGreaterEqual(n, 5, "%s 的题太少：%d" % (key, n))

    def test_ids_and_prior_are_consistent(self):
        self.assertEqual(len({it["id"] for it in B.ITEMS}), len(B.ITEMS))
        for it in B.ITEMS:
            self.assertAlmostEqual(it["difficulty_prior"], B.prior(it["band"], it["steps"], it["ops"]), places=9)

    def test_prior_grows_with_steps_and_stage(self):
        self.assertLess(B.prior("primary", 1, 1), B.prior("middle", 1, 1))
        self.assertLess(B.prior("middle", 1, 1), B.prior("high", 1, 1))
        self.assertLess(B.prior("middle", 2, 3), B.prior("middle", 3, 5))


class AbilityTest(unittest.TestCase):
    def test_mastery_maps_to_the_same_scale(self):
        self.assertAlmostEqual(B.theta_from_mastery(0.5), 0.5)
        self.assertLess(B.theta_from_mastery(0.2), B.theta_from_mastery(0.8))

    def test_at_equal_ability_and_difficulty_it_is_a_coin_flip(self):
        self.assertAlmostEqual(B.p_correct(0.6, 0.6), 0.5)

    def test_target_difficulty_is_easier_than_the_student(self):
        self.assertLess(B.target_difficulty(0.6), 0.6)
        self.assertAlmostEqual(B.p_correct(0.6, B.target_difficulty(0.6)), B.TARGET_P, places=3)


class SelectTest(unittest.TestCase):
    def test_it_picks_the_closest_item(self):
        item, why = B.select("数学", "一元一次方程", theta=0.45)
        self.assertIsNotNone(item)
        self.assertLess(abs(item["difficulty_prior"] - B.target_difficulty(0.45)), 0.35)
        self.assertIn("难度", why)

    def test_excluded_items_are_skipped(self):
        first, _ = B.select("数学", "表内乘法", theta=0.3)
        second, _ = B.select("数学", "表内乘法", theta=0.3, exclude={first["id"]})
        self.assertNotEqual(first["id"], second["id"])

    def test_unknown_topic_returns_nothing(self):
        self.assertEqual(B.select("数学", "不存在的知识点", theta=0.5), (None, None))

    def test_a_well_attempted_item_loses_to_a_fresh_one(self):
        topic = "表内乘法"
        items = [it for it in B.ITEMS if it["topic"] == topic]
        stats = {it["id"]: {"attempts": 3, "correct": 3, "difficulty": it["difficulty_prior"]} for it in items[:-1]}
        pick, _ = B.select("数学", topic, theta=0.3, stats=stats)
        self.assertEqual(pick["id"], items[-1]["id"])


class CheckTest(unittest.TestCase):
    def test_numeric_and_fraction_answers_match(self):
        it = next(x for x in B.ITEMS if x["params"]["kind"] == "fracadd")
        self.assertTrue(B.check(it, it["answer"]))
        frac = next(x for x in B.ITEMS if x["params"]["kind"] == "fracadd")
        self.assertTrue(B.check(frac, str(float(Fraction(frac["answer"])))))

    def test_units_are_ignored(self):
        it = next(x for x in B.ITEMS if x.get("unit") == "厘米")
        self.assertTrue(B.check(it, it["answer"] + "厘米"))

    def test_wrong_and_empty_answers_are_false(self):
        it = B.ITEMS[0]
        self.assertFalse(B.check(it, "0"))
        self.assertFalse(B.check(it, "   "))


    def test_text_answers_ignore_punctuation_and_width(self):
        item = {"answer": "黄河入海流", "unit": "", "params": {"kind": "dictation"}}
        self.assertTrue(B.check(item, "黄河入海流"))
        self.assertTrue(B.check(item, "黄河入海流。"))
        self.assertTrue(B.check(item, " 黄河入海流 "))
        self.assertFalse(B.check(item, "黄河入海"))
        self.assertFalse(B.check(item, ""))

    def test_english_answers_are_case_insensitive_but_exact(self):
        item = {"answer": "went", "unit": "", "params": {"kind": "verb_past"}}
        self.assertTrue(B.check(item, "Went"))
        self.assertTrue(B.check(item, "went."))
        self.assertFalse(B.check(item, "goed"))

class CalibrationTest(unittest.TestCase):
    def test_correct_answer_makes_the_item_easier_and_the_student_stronger(self):
        theta, d = B.update_pair(0.50, 0.60, True)
        self.assertGreater(theta, 0.50)
        self.assertLess(d, 0.60)

    def test_wrong_answer_makes_the_item_harder(self):
        theta, d = B.update_pair(0.50, 0.60, False)
        self.assertLess(theta, 0.50)
        self.assertGreater(d, 0.60)

    def test_steps_shrink_as_attempts_grow(self):
        _, d1 = B.update_pair(0.40, 0.60, True, attempts=0)
        _, d2 = B.update_pair(0.40, 0.60, True, attempts=40)
        self.assertGreater(0.60 - d1, 0.60 - d2)

    def test_difficulty_stays_inside_bounds(self):
        _, d = B.update_pair(0.01, 0.05, True, attempts=0)
        self.assertGreaterEqual(d, 0.02)


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DB(os.path.join(self.tmp, "t.db"))

    def test_an_attempt_is_logged_and_the_difficulty_moves(self):
        it = B.ITEMS[0]
        before, after, n = self.db.record_item_attempt(it["id"], it["subject"], it["topic"], 0.45,
                                                       it["difficulty_prior"], True, it["answer"])
        self.assertEqual(n, 1)
        self.assertLess(after, before)
        row = self.db.item_stat(it["id"])
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["correct"], 1)
        self.assertAlmostEqual(row["difficulty"], after)

    def test_repeated_attempts_accumulate(self):
        it = B.ITEMS[0]
        for _ in range(3):
            self.db.record_item_attempt(it["id"], it["subject"], it["topic"], 0.5, it["difficulty_prior"], False)
        self.assertEqual(self.db.item_stat(it["id"])["attempts"], 3)
        self.assertEqual(self.db.item_stat(it["id"])["correct"], 0)


if __name__ == "__main__":
    unittest.main()
