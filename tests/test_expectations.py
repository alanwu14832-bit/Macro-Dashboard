"""公布前的預期。

本站沒有市場共識，但有三種公開的預期，性質不同、頁面上各寫各的名字：
利率決議的期貨定價（市場）、通膨與 GDP 的聯準銀行模型預估（模型）、其餘的沒有。
這裡釘住的都是「不會報錯、只會讓頁面說謊」的地方：

  1. 模型不是共識：一律寫「模型預估」「期貨定價」，沒有來源的發布什麼都不加。
  2. 預估要跟同一期的實際值比。來源隔天才登錄實際值，公布當晚不能拿上個月的成績充數。
  3. 公布當天的那一筆預估不算——它可能已經看過答案。
  4. 從未公布的月份（2025-10 的 CPI）不能被當成「下一期」。
  5. 太舊的預估不登；抓不到要講明，不留一個看起來像「沒有預期」的空白。
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from unittest import mock

from macro.compute import expectations as ex
from macro.data import Bundle
from macro.render.pages import front_blocks as front
from macro.render.pages import frontpage, release
from macro.series import Series
from macro.sources import nowcast


# ------------------------------------------------------------ 來源的格式 ----

def chart(target: str, labels: list, lines: dict) -> dict:
    """一張圖：labels 裡的 tuple 是公布日的直線標記（不是資料點）。"""
    category = [({"vline": "true", "label": item[0]} if isinstance(item, tuple) else {"label": item})
                for item in labels]
    return {"chart": {"subcaption": target}, "categories": [{"category": category}],
            "dataset": [{"seriesname": name, "data": [{"value": v} for v in values]}
                        for name, values in lines.items()]}


class Parsing(unittest.TestCase):
    def test_release_markers_are_not_data_points(self):
        """直線標記夾在標籤中間，資料陣列卻沒有那一格——不拿掉會整條線錯位一天。"""
        raw = json.dumps([chart("2026-08", ["08/31", "09/10", ("CPI Aug",), "09/11"], {
            "CPI Inflation": ["3.10", "3.20", "3.25"],
            "Actual CPI Inflation": ["", "", "3.30"],
        })])
        slot = nowcast.parse(raw)[(2026, 8)]["cpi"]
        self.assertEqual(slot["path"], [(date(2026, 8, 31), 3.10), (date(2026, 9, 10), 3.20),
                                        (date(2026, 9, 11), 3.25)])
        self.assertEqual(slot["actual"], (date(2026, 9, 11), 3.30))

    def test_labels_have_no_year_so_january_belongs_to_the_next_one(self):
        raw = json.dumps([chart("2025-12", ["12/15", "01/13"], {
            "Core PCE Inflation": ["2.9", "3.0"]})])
        path = nowcast.parse(raw)[(2025, 12)]["core_pce"]["path"]
        self.assertEqual([d for d, _ in path], [date(2025, 12, 15), date(2026, 1, 13)])

    def test_unknown_lines_and_blank_values_are_skipped(self):
        raw = json.dumps([chart("2026-09", ["09/01", "09/02"], {
            "PCE Inflation": ["", "3.5"], "Something Else": ["1", "2"]})])
        month = nowcast.parse(raw)[(2026, 9)]
        self.assertEqual(list(month), ["pce"])
        self.assertEqual(month["pce"]["path"], [(date(2026, 9, 2), 3.5)])
        self.assertIsNone(month["pce"]["actual"])

    def test_a_changed_format_raises_instead_of_returning_nothing(self):
        """回一個看起來正常的空結果，頁面會默默變成「沒有預期」。"""
        for raw in ("{}", "[]", json.dumps([chart("2026-09", ["09/01"], {"Other": ["1"]})])):
            with self.assertRaises(Exception):
                nowcast.parse(raw)

    def test_only_the_recent_months_are_kept(self):
        raw = json.dumps([chart(f"2026-{m:02d}", [f"{m:02d}/15"], {"CPI Inflation": ["3.0"]})
                          for m in range(1, 10)])
        self.assertEqual(sorted(nowcast.parse(raw, keep=3)), [(2026, 7), (2026, 8), (2026, 9)])

    def test_the_saved_copy_round_trips(self):
        raw = json.dumps([chart("2026-08", ["08/31", ("CPI Aug",), "09/11"], {
            "CPI Inflation": ["3.1", "3.2"], "Actual CPI Inflation": ["", "3.3"]})])
        parsed = nowcast.parse(raw)
        self.assertEqual(nowcast._unpack(nowcast._pack(parsed)), parsed)

    def test_an_html_error_page_is_not_cached_as_data(self):
        self.assertFalse(nowcast._looks_right("<html>Access Denied</html>"))
        self.assertFalse(nowcast._looks_right('[{"seriesname": "CPI Inflation"}]'))

    def test_a_failed_fetch_says_why(self):
        with mock.patch.object(nowcast, "get", side_effect=OSError("403")):
            self.assertIsNone(nowcast.fetch())
        self.assertIn("克里夫蘭", nowcast.LAST_ERROR)
        self.assertIn("403", nowcast.LAST_ERROR)


# ------------------------------------------------------------ 通膨的預估 ----

def slot(path, actual=None):
    return {"path": path, "actual": actual}


def inflation_data(*, pending_last=date(2026, 10, 9)) -> dict:
    """四個月：2025-10 從未公布、7 月與 8 月已公布、9 月還沒。"""
    def kind(shift):
        return {
            (2025, 10): {"cpi": slot([(date(2025, 11, 10), 3.0 + shift)])},
            (2026, 7): {"cpi": slot([(date(2026, 8, 11), 2.90 + shift), (date(2026, 8, 12), 2.70 + shift)],
                                    (date(2026, 8, 12), 2.70 + shift))},
            (2026, 8): {"cpi": slot([(date(2026, 9, 10), 3.00 + shift)], (date(2026, 9, 11), 3.10 + shift))},
            (2026, 9): {"cpi": slot([(date(2026, 10, 8), 3.50 + shift), (pending_last, 3.60 + shift)])},
        }
    return {"yoy": kind(0.0), "mom": kind(-3.0)}


class InflationNowcast(unittest.TestCase):
    TODAY = date(2026, 10, 10)

    def test_the_next_release_is_the_month_after_the_last_published_one(self):
        """2025-10 的 CPI 因政府關門從未公布，它永遠「沒有實際值」，但不是下一期。"""
        item = ex.inflation_measure(inflation_data(), "cpi", self.TODAY)
        self.assertEqual(item["next"]["target"], (2026, 9))
        self.assertAlmostEqual(item["next"]["yoy"], 3.60)
        self.assertAlmostEqual(item["next"]["mom"], 0.60)
        self.assertEqual(item["next"]["as_of"], date(2026, 10, 9))

    def test_the_release_day_estimate_does_not_count(self):
        """7 月：公布當天模型改成 2.70（跟實際一樣）。成績單要用前一天的 2.90。"""
        item = ex.inflation_measure(inflation_data(), "cpi", self.TODAY)
        july = item["history"][0]
        self.assertEqual(july["target"], (2026, 7))
        self.assertAlmostEqual(july["yoy_nowcast"], 2.90)
        self.assertAlmostEqual(july["yoy_error"], -0.20)

    def test_the_track_record_is_the_average_miss(self):
        item = ex.inflation_measure(inflation_data(), "cpi", self.TODAY)
        self.assertEqual(item["track"]["n"], 2)
        self.assertAlmostEqual(item["track"]["yoy_mae"], 0.15)      # |−0.20| 與 |+0.10|
        self.assertAlmostEqual(item["track"]["yoy_bias"], -0.05)
        self.assertAlmostEqual(item["track"]["yoy_worst"], -0.20)
        self.assertEqual(item["last"]["target"], (2026, 8))
        self.assertEqual(item["kind"], "model")

    def test_a_stale_estimate_is_not_shown(self):
        item = ex.inflation_measure(inflation_data(), "cpi", date(2026, 10, 25))
        self.assertIsNone(item["next"])
        self.assertEqual(len(item["history"]), 2)                    # 成績單還在

    def test_nothing_to_say_returns_nothing(self):
        data = {"yoy": {(2026, 9): {"cpi": slot([])}}, "mom": {(2026, 9): {"cpi": slot([])}}}
        self.assertIsNone(ex.inflation_measure(data, "cpi", self.TODAY))

    def test_one_broken_measure_does_not_take_the_others_down(self):
        data = inflation_data()
        for kind in ("yoy", "mom"):
            for month in data[kind].values():
                month["core_cpi"] = {"path": "不是清單", "actual": 1}
        with mock.patch.object(nowcast, "fetch", return_value=data), \
             mock.patch.object(ex.clock, "us_today", return_value=self.TODAY):
            out = ex.compute(Bundle())
        self.assertEqual(list(out["items"]), ["cpi"])

    def test_a_failed_fetch_is_reported_not_hidden(self):
        def failing():
            nowcast.LAST_ERROR = "克里夫蘭聯準銀行 Inflation Nowcasting（mom）拿不到或讀不懂：403"
            return None
        with mock.patch.object(nowcast, "fetch", side_effect=failing):
            out = ex.compute(Bundle())
        self.assertEqual(out["items"], {})
        self.assertIn("拿不到", out["error"])


# ----------------------------------------------------------------- GDPNow ----

def quarterly(series_id, pairs):
    return Series.from_pairs(series_id, pairs, frequency="q")


class GDPNow(unittest.TestCase):
    def bundle(self, *, actual_through_q3=False):
        b = Bundle()
        b.add("GDPNOW", quarterly("GDPNOW", [(date(2026, 1, 1), 2.0), (date(2026, 4, 1), 3.0),
                                             (date(2026, 7, 1), 3.6)]))
        actual = [(date(2026, 1, 1), 1.5), (date(2026, 4, 1), 3.8)]
        if actual_through_q3:
            actual.append((date(2026, 7, 1), 3.1))
        b.add("A191RL1Q225SBEA", quarterly("A191RL1Q225SBEA", actual))
        return b

    def test_the_unpublished_quarter_is_the_estimate(self):
        item = ex.gdp(self.bundle())
        self.assertEqual(item["next"], {"target": (2026, 7), "value": 3.6})
        self.assertEqual([row["target"] for row in item["history"]], [(2026, 1), (2026, 4)])
        self.assertAlmostEqual(item["track"]["mae"], 0.65)          # |−0.5| 與 |+0.8|
        self.assertEqual(ex.before(item), "2026 年 Q3 年化季增 3.6%")

    def test_the_gap_is_written_to_the_same_precision_as_the_numbers(self):
        """「預估 3.0%、現在的數字 3.8%，高 0.80」像是兩套數字。GDP 一律一位小數。"""
        text = ex.after(ex.gdp(self.bundle()))
        self.assertIn("2026 年 Q2 預估 3.0%、現在的數字 3.8%，高 0.8 個百分點", text)
        self.assertRegex(text, r"近 2 期平均差 0\.\d；")             # 一位小數，不是 0.65

    def test_once_published_there_is_no_estimate_left(self):
        item = ex.gdp(self.bundle(actual_through_q3=True))
        self.assertIsNone(item["next"])
        self.assertEqual(item["last"]["target"], (2026, 7))
        self.assertEqual(ex.before(item), "")

    def test_no_series_no_item(self):
        self.assertIsNone(ex.gdp(Bundle()))


# ------------------------------------------------------------ 頁面上的話 ----

def cpi_item(**over) -> dict:
    item = {"key": "cpi", "name": "CPI", "kind": "model", "source": nowcast.SOURCE,
            "source_url": nowcast.PAGE,
            "next": {"target": (2026, 9), "yoy": 3.60, "mom": 0.53, "as_of": date(2026, 10, 9)},
            "last": {"target": (2026, 8), "mom_nowcast": 0.30, "mom_actual": 0.38, "mom_error": 0.08,
                     "yoy_nowcast": 3.00, "yoy_actual": 3.10, "yoy_error": 0.10,
                     "released": date(2026, 9, 11), "nowcast_date": date(2026, 9, 10)},
            "track": {"n": 24, "mom_mae": 0.08, "yoy_mae": 0.07, "mom_bias": 0.0, "yoy_bias": 0.0,
                      "mom_worst": 0.2, "yoy_worst": -0.39}}
    item["history"] = [item["last"]]
    item.update(over)
    return item


def core_pce_item(yoy=3.02) -> dict:
    return cpi_item(key="core_pce", name="核心 PCE",
                    next={"target": (2026, 9), "yoy": yoy, "mom": 0.25, "as_of": date(2026, 10, 9)},
                    track={"n": 24, "mom_mae": 0.06, "yoy_mae": 0.09, "mom_worst": 0.1,
                           "yoy_worst": 0.39})


def context(**items) -> dict:
    return {"expectations": {"items": items, "error": None}}


class Wording(unittest.TestCase):
    def test_before_names_both_rates(self):
        self.assertEqual(ex.before(cpi_item()), "CPI 年增 3.60%、月增 0.53%")
        self.assertEqual(ex.before(cpi_item(next=None)), "")

    def test_after_measures_the_miss_against_the_usual_miss(self):
        usual = ex.after(cpi_item())
        self.assertIn("8 月 CPI 月增：預估 0.30%、實際 0.38%，高 0.08 個百分點", usual)
        self.assertIn("近 24 期平均差 0.08", usual)
        self.assertIn("這次在平常的誤差內", usual)
        last = dict(cpi_item()["last"], mom_actual=0.14, mom_error=-0.16)
        self.assertIn("低 0.16 個百分點", ex.after(cpi_item(last=last)))
        self.assertIn("這次是平常的 2.0 倍", ex.after(cpi_item(last=last)))
        same = dict(cpi_item()["last"], mom_actual=0.30, mom_error=0.0)
        self.assertIn("跟預估一樣", ex.after(cpi_item(last=same)))

    def test_a_miss_is_never_called_better_or_worse(self):
        """高於預估的通膨不是「優於預期」。只寫高低與幅度。"""
        text = ex.after(cpi_item()) + ex.before(cpi_item())
        for word in ("優於", "不如", "遜於", "共識", "市場預期"):
            self.assertNotIn(word, text)

    def test_each_kind_of_expectation_carries_its_own_name(self):
        ctx = context(cpi=cpi_item(), core_cpi=cpi_item(key="core_cpi", name="核心 CPI"))
        self.assertTrue(front.model_estimate(ctx, "CPIAUCSL").startswith("模型預估：CPI 年增 3.60%"))
        self.assertIn("；核心 CPI 年增", front.model_estimate(ctx, "CPIAUCSL"))
        pricing = front.futures_pricing({"next": {"probs": {"hold": 0.88, "cut25": 0.12,
                                                            "hike25": 0.001}}})
        self.assertEqual(pricing, "期貨定價：不動 88%、降息 1 碼 12%")

    def test_releases_without_a_source_get_nothing(self):
        ctx = context(cpi=cpi_item())
        for series_id in ("PAYEMS", "UNRATE", "RSAFS", None):
            self.assertEqual(front.model_estimate(ctx, series_id), "")
        self.assertFalse(ex.has_source("PAYEMS"))
        self.assertEqual(front.futures_pricing(None), "")
        self.assertEqual(front.futures_pricing({"next": {}}), "")


class GateOutlook(unittest.TestCase):
    GATE = {"series": "PCEPILFE", "line": 2.8, "cross": "below", "gap": 0.21}
    ROWS = {"rows": [{"id": "PCEPILFE", "next_release": date(2026, 10, 29), "days_away": 19}]}

    def test_says_when_and_which_side_of_the_line(self):
        ctx = {**context(core_pce=core_pce_item()), "freshness": self.ROWS}
        text = front.gate_outlook(ctx, self.GATE)
        self.assertIn("下一次公布 10/29（19 天後）", text)
        self.assertIn("模型預估 9 月 核心 PCE 年增 3.02%，仍在 2.8% 這條線的上方", text)
        self.assertIn("這個模型平常差 0.09 個百分點", text)

    def test_says_so_when_the_estimate_is_already_across(self):
        ctx = {**context(core_pce=core_pce_item(2.75)), "freshness": self.ROWS}
        self.assertIn("已經越過 2.8% 這條線", front.gate_outlook(ctx, self.GATE))

    def test_without_an_estimate_only_the_date_is_left(self):
        text = front.gate_outlook({"freshness": self.ROWS}, self.GATE)
        self.assertEqual(text, "下一次公布 10/29（19 天後）。")
        self.assertNotIn("模型", text)

    def test_gates_not_tied_to_one_series_say_nothing(self):
        self.assertEqual(front.gate_outlook(context(core_pce=core_pce_item()), {"gap": 3.0}), "")


# ------------------------------------------------------------ 今天的事件 ----

def monthly(series_id, last=(2026, 9)):
    year, month = last
    return Series.from_pairs(series_id, [(date(year, month - 1, 1), 100.0), (date(year, month, 1), 100.5)],
                             frequency="m")


class TodaysEvents(unittest.TestCase):
    def ctx(self, item):
        bundle = Bundle()
        bundle.add("CPIAUCSL", monthly("CPIAUCSL"))
        return {**context(cpi=item), "_bundle": bundle,
                "fedfunds": {"next": {"probs": {"hold": 0.88, "cut25": 0.12}}}}

    PENDING = {"id": "CPIAUCSL", "kind": "data", "region": "美國", "tag": "美國數據　今晚公布",
               "title": "CPI", "detail": "約台北 20:30。"}
    RELEASED = {**PENDING, "tag": "美國數據　已公布", "detail": "台北 10/15 20:30 公布。"}

    def test_before_the_release_the_estimate_is_attached(self):
        event = front.expected(self.ctx(cpi_item()), self.PENDING)
        self.assertEqual(event["expect"], "模型預估：CPI 年增 3.60%、月增 0.53%")
        self.assertTrue(event["detail"].endswith("模型預估：CPI 年增 3.60%、月增 0.53%。"))

    def test_after_the_release_the_miss_is_only_for_the_same_period(self):
        """本站已經有 9 月的 CPI；來源也登錄了 9 月的實際值，才寫差多少。"""
        last = dict(cpi_item()["last"], target=(2026, 9))
        event = front.expected(self.ctx(cpi_item(last=last, next=None)), self.RELEASED)
        self.assertTrue(event["expect"].startswith("模型預估對實際：9 月 CPI 月增"))

    def test_last_months_score_is_not_passed_off_as_tonights(self):
        """公布當晚來源還停在 8 月：只列公布前的預估，不把 8 月的差距寫成今天的。"""
        event = front.expected(self.ctx(cpi_item()), self.RELEASED)
        self.assertEqual(event["expect"], "公布前的模型預估：CPI 年增 3.60%、月增 0.53%")
        self.assertNotIn("8 月", event["expect"])

    def test_no_matching_period_means_no_sentence(self):
        item = cpi_item(next={"target": (2026, 10), "yoy": 3.4, "mom": 0.2, "as_of": date(2026, 10, 16)})
        event = front.expected(self.ctx(item), self.RELEASED)
        self.assertNotIn("expect", event)

    def test_a_release_without_a_source_is_left_alone(self):
        payrolls = {**self.PENDING, "id": "PAYEMS", "title": "非農就業"}
        self.assertIs(front.expected(self.ctx(cpi_item()), payrolls), payrolls)

    def test_a_pending_fomc_gets_the_futures_pricing_and_nothing_else_does(self):
        ctx = self.ctx(cpi_item())
        pending = {"kind": "policy", "region": "美國", "policy": "待公布", "detail": ""}
        self.assertEqual(front.expected(ctx, pending)["expect"], "期貨定價：不動 88%、降息 1 碼 12%")
        decided = {**pending, "policy": "不變"}
        self.assertIs(front.expected(ctx, decided), decided)
        taiwan = {**pending, "region": "台灣"}
        self.assertIs(front.expected(ctx, taiwan), taiwan)

    def test_the_whole_list_is_enriched_once(self):
        events = {"events": [self.PENDING], "summary": "一項數據"}
        out = front.with_expectations(self.ctx(cpi_item()), events)
        self.assertIn("expect", out["events"][0])
        self.assertEqual(out["summary"], "一項數據")
        self.assertNotIn("expect", events["events"][0])              # 不改原本那一份
        self.assertEqual(front.with_expectations({}, None), {})

    def test_the_headline_deck_carries_it(self):
        bundle = Bundle()
        bundle.add("CPIAUCSL", Series.from_pairs(
            "CPIAUCSL", [(date(2025 + (m > 9), (m + 2) % 12 + 1, 1), 300.0 + m) for m in range(14)],
            frequency="m"))
        event = {**self.RELEASED, "expect": "公布前的模型預估：CPI 年增 3.60%、月增 0.53%"}
        lede = frontpage.data_lede(event, bundle)
        self.assertIn("公布前的模型預估：CPI 年增 3.60%、月增 0.53%。", lede["deck"])


class ComingUp(unittest.TestCase):
    def test_only_items_with_a_source_get_an_expectation_line(self):
        ctx = {**context(cpi=cpi_item()),
               "fedfunds": {"next": {"probs": {"hold": 0.88, "cut25": 0.12}}},
               "freshness": {"imminent": [
                   {"id": "CPIAUCSL", "name": "CPI", "days_away": 5, "frequency": "m"},
                   {"id": "RSAFS", "name": "零售銷售", "days_away": 6, "frequency": "m"}]}}
        fomc = {"days": 19, "date": date(2026, 10, 28)}
        with mock.patch("macro.sources.treasury.upcoming", return_value=[]), \
             mock.patch.object(front, "_next_opex", return_value=None):
            items = {item["what"]: item for item in front.upcoming(ctx, fomc)}
            html = front.next_up(ctx, {"transitions": []}, fomc)
        self.assertEqual(items["CPI"]["expect"], "模型預估：CPI 年增 3.60%、月增 0.53%")
        self.assertEqual(items["零售銷售"]["expect"], "")
        self.assertTrue(items["FOMC 利率決策（10/28）"]["expect"].startswith("期貨定價："))
        self.assertEqual(html.count('<p class="expect">'), 2)
        self.assertIn("市場共識是付費資料", html)


# ------------------------------------------------------------- 發布落點頁 ----

class ReleasePage(unittest.TestCase):
    def test_a_release_without_a_source_keeps_the_plain_statement(self):
        self.assertEqual(release._expectation_block(context(cpi=cpi_item()), "PAYEMS"), "")
        self.assertFalse(release._has_model("PAYEMS"))
        self.assertTrue(release._has_model("CPIAUCSL"))

    def test_the_block_shows_estimate_track_record_and_source(self):
        html = release._expectation_block(context(cpi=cpi_item()), "CPIAUCSL")
        self.assertIn("公布前的預期", html)
        self.assertIn("模型預估 CPI 年增 3.60%、月增 0.53%（10/9 的估計）", html)
        self.assertIn("近 24 期平均差：月增 0.08、年增 0.07 個百分點", html)
        self.assertIn("不是市場共識，也不是市場定價", html)
        self.assertIn(nowcast.PAGE, html)

    def test_a_failed_fetch_is_said_out_loud(self):
        ctx = {"expectations": {"items": {}, "error": "克里夫蘭聯準銀行 Inflation Nowcasting（mom）拿不到"}}
        html = release._expectation_block(ctx, "CPIAUCSL")
        self.assertIn("拿不到", html)
        self.assertIn("這一格留白，不拿前值代替", html)

    def test_the_page_never_calls_the_model_a_consensus(self):
        self.assertIn("不是共識", release.MODEL_NOT_CONSENSUS)
        self.assertIn("沒有市場共識預期", release.MODEL_NOT_CONSENSUS)

    def test_the_history_table_is_short(self):
        rows = [dict(cpi_item()["last"], target=(2026, m)) for m in range(1, 9)]
        html = release._expectation_block(context(cpi=cpi_item(history=rows)), "CPIAUCSL")
        self.assertEqual(html.count(">2026-"), 6)                    # 只列最近六期
        self.assertIn("2026-08", html)
        self.assertNotIn("2026-02", html)


if __name__ == "__main__":
    unittest.main()
