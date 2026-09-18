"""台灣央行理監事會決議不准遺漏。

2026-09-17 理監事會維持利率、把第 2 戶房貸成數上限從 6 成放寬到 7 成，
網站完全沒顯示：它只讀貼放利率表，而那張表只在利率有變時才多一列。

固定資料是歷次決議新聞稿的原句（2020 降息、2024 升息、2024 調準備率與
信用管制、2025 只用過去式提到信用管制、2026 放寬成數）。
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from macro import cbc_board
from macro.clock import TAIPEI
from macro.series import Series
from macro.sources import cbc

CUT_2020 = ("(一) 本行重貼現率、擔保放款融通利率及短期融通利率各調降0.25個百分點，分別由年息"
            "1.375%、1.75%及3.625%調整為1.125%、1.5%及3.375%，自本年3月20日起實施。")
HIKE_2024 = ("本行重貼現率、擔保放款融通利率及短期融通利率各調升0.125個百分點，分別由年息"
             "1.875%、2.25%及4.125%調整為2%、2.375%及4.25%，自本年3月22日起實施。")
HOLD = "本行重貼現率、擔保放款融通利率及短期融通利率，分別維持年息2%、2.375%及4.25%。"
SEPT_2024 = (HOLD + "茲修正「中央銀行對金融機構辦理不動產抵押貸款業務規定」，自本年9月20日起實施。"
             "2. 自然人第2戶購屋貸款最高成數由6成降為5成，並擴大實施地區至全國。"
             "3. 公司法人購置住宅貸款、自然人購置高價住宅貸款及第3戶(含)以上購屋貸款之最高成數由4成降為3成。"
             "新台幣活期性及定期性存款準備率各調升0.25個百分點，自本年10月1日起實施(詳附件2)。"
             "此外，本行認為搭配調升存款準備率。業務聯繫單位：秘書處 附件1 第2戶購屋貸款 6成 5成")
PAST_TENSE_2025 = (HOLD + "四、本行於上年8月中旬採取道德勸說，嗣於同年9月第七度調整選擇性信用管制措施。"
                   "督促銀行落實本行選擇性信用管制措施。")
SEPT_2026 = (HOLD + "四、本行理事同意調整選擇性信用管制措施 自本年3月本行適度調整全國自然人第2戶"
             "購屋貸款之成數上限以來。爰適度調整相關信用管制措施，並配合修正「中央銀行對金融機構"
             "辦理不動產抵押貸款業務規定」，自本年9月18日起實施(詳附件)，主要修正重點如下： (一) "
             "為進一步協助自然人第2戶貸款供家人或自己購屋自住之需求，爰調整自然人第2戶購屋貸款最高"
             "成數上限，由6成調升為7成。業務聯繫單位：秘書處聯絡科 附件 第2戶購屋貸款 6成 7成")


class Parse(unittest.TestCase):
    def test_cut(self):
        rate = cbc.parse_board_decision(CUT_2020, 2020)["rate"]
        self.assertEqual(rate, {"action": "lower", "step": 0.25, "from": 1.375,
                                "to": 1.125, "effective": "2020-03-20"})

    def test_hike_by_half_a_quarter(self):
        rate = cbc.parse_board_decision(HIKE_2024, 2024)["rate"]
        self.assertEqual((rate["action"], rate["step"], rate["to"], rate["effective"]),
                         ("raise", 0.125, 2.0, "2024-03-22"))

    def test_hold_with_reserve_ratio_and_credit_controls(self):
        d = cbc.parse_board_decision(SEPT_2024, 2024)
        self.assertEqual(d["rate"]["action"], "hold")
        self.assertEqual(d["reserve"], {"action": "raise", "step": 0.25, "effective": "2024-10-01"})
        self.assertEqual(d["credit"]["effective"], "2024-09-20")

    def test_one_clause_lists_every_loan_type_it_changes(self):
        """一句話同時動三類貸款，只列最近的一類會讓人以為只動了第 3 戶。"""
        changes = cbc.parse_board_decision(SEPT_2024, 2024)["credit"]["changes"]
        self.assertEqual(changes, [
            "第 2 戶購屋貸款成數上限 6 成 → 5 成",
            "公司法人購置住宅貸款、高價住宅貸款、第 3 戶以上購屋貸款成數上限 4 成 → 3 成",
        ])

    def test_past_tense_mention_of_credit_controls_is_not_a_change(self):
        """2024-12 以後每份新聞稿都提到「第七度調整選擇性信用管制措施」。"""
        d = cbc.parse_board_decision(PAST_TENSE_2025, 2025)
        self.assertIsNone(d["credit"])
        self.assertIsNone(d["reserve"])

    def test_attachment_table_is_not_read_twice(self):
        d = cbc.parse_board_decision(SEPT_2026, 2026)
        self.assertEqual(d["credit"]["changes"], ["第 2 戶購屋貸款成數上限 6 成 → 7 成"])

    def test_no_rate_sentence_is_none(self):
        self.assertIsNone(cbc.parse_board_decision("本行將持續關注。", 2026))

    def test_schedule_ignores_the_notice_date(self):
        text = ("發布日期 114年12月18日 115年中央銀行理監事聯席會議預定日期 115年3月19日 "
                "115年6月18日 115年9月17日 115年12月17日")
        self.assertEqual(cbc.parse_schedule(text, 115),
                         [date(2026, 3, 19), date(2026, 6, 18), date(2026, 9, 17), date(2026, 12, 17)])


class Latest(unittest.TestCase):
    def _run(self, newest, previous):
        pages = {"u1": "發布日期：2026-09-17 " + newest, "u2": "發布日期：2026-06-18 " + previous}
        items = [{"title": cbc.DECISION_TITLE, "link": "u1"},
                 {"title": "115年9月17日央行理監事會後記者會參考資料", "link": "x"},
                 {"title": cbc.DECISION_TITLE, "link": "u2"}]
        with mock.patch.object(cbc, "get", side_effect=lambda url, **_: pages[url]):
            return cbc.latest_board_decision(items=items)

    def test_ok_carries_previous_action(self):
        out = self._run(SEPT_2026, HOLD)
        self.assertEqual((out["status"], out["date"], out["prev_action"]), ("ok", "2026-09-17", "hold"))

    def test_move_that_does_not_start_from_the_previous_rate_is_rejected(self):
        """上次決議到 2%，這次卻寫「由 1.875% 調升」——對不上就不採用。"""
        out = self._run(HIKE_2024, HOLD.replace("年息2%", "年息2.125%"))
        self.assertEqual(out["status"], "unparsed")

    def test_no_decision_notice_is_unavailable(self):
        self.assertEqual(cbc.latest_board_decision(items=[])["status"], "unavailable")


def tpe(y, m, d, hh=10, mm=0):
    return datetime.combine(date(y, m, d), time(hh, mm), tzinfo=TAIPEI)


def ok(day, **decision):
    parsed = cbc.parse_board_decision(SEPT_2026, 2026)
    return {"status": "ok", "date": day, "url": "u", **parsed, "prev_action": "hold", **decision}


SCHEDULE = cbc_board.meetings()


class Status(unittest.TestCase):
    def test_announced_with_headline_and_details(self):
        state = cbc_board.decision_status(ok("2026-09-17"), SCHEDULE, tpe(2026, 9, 17, 18))
        self.assertEqual(state["state"], "announced")
        self.assertEqual(state["headline"], "台灣央行利率不變（重貼現率 2%）；調整房貸信用管制")
        self.assertIn("第 2 戶購屋貸款成數上限 6 成 → 7 成", state["details"])
        self.assertTrue(state["change"])

    def test_meeting_afternoon_is_pending_then_missing(self):
        old = ok("2026-06-18")
        self.assertEqual(cbc_board.decision_status(old, SCHEDULE, tpe(2026, 9, 17, 15))["state"], "pending")
        self.assertEqual(cbc_board.decision_status(old, SCHEDULE, tpe(2026, 9, 17, 18))["state"], "missing")

    def test_quiet_week(self):
        self.assertIsNone(cbc_board.decision_status(ok("2026-06-18"), SCHEDULE, tpe(2026, 8, 1)))

    def test_step_labels(self):
        hike = {"rate": {"action": "raise", "step": 0.125, "from": 1.875, "to": 2.0}}
        self.assertEqual(cbc_board.headline(hike), "台灣央行升息 半碼（重貼現率 1.875% → 2%）")
        cut = {"rate": {"action": "lower", "step": 0.25, "from": 1.375, "to": 1.125}}
        self.assertIn("降息 1 碼", cbc_board.headline(cut))


class Reconcile(unittest.TestCase):
    RATE = cbc.rate_series([(date(2023, 3, 24), 1.875)], today=date(2026, 9, 30))

    def test_hold_changes_nothing(self):
        rate, result = cbc_board.reconcile_discount(self.RATE, ok("2026-09-17"))
        self.assertFalse(result["patched"])
        self.assertIs(rate, self.RATE)

    def test_move_not_yet_in_the_table_is_patched_as_a_step(self):
        decision = {"status": "ok", "date": "2026-09-17",
                    "rate": {"action": "raise", "step": 0.125, "from": 1.875, "to": 2.0,
                             "effective": "2026-09-18"}}
        rate, result = cbc_board.reconcile_discount(self.RATE, decision, today=date(2026, 9, 30))
        self.assertTrue(result["patched"])
        self.assertEqual((rate["changes"].last_date, rate["changes"].last), (date(2026, 9, 18), 2.0))
        self.assertEqual(rate["monthly"].last, 2.0)
        self.assertEqual(rate["monthly"].value_on(date(2026, 8, 1)), 1.875)
        self.assertEqual(rate["changes"].meta["patched_from"]["statement"], "2026-09-17")

    def test_table_already_has_it(self):
        table = cbc.rate_series([(date(2023, 3, 24), 1.875), (date(2026, 9, 18), 2.0)],
                                today=date(2026, 9, 30))
        decision = {"status": "ok", "date": "2026-09-17",
                    "rate": {"action": "raise", "step": 0.125, "from": 1.875, "to": 2.0,
                             "effective": "2026-09-18"}}
        rate, result = cbc_board.reconcile_discount(table, decision)
        self.assertEqual((result["patched"], result["conflict"]), (False, False))


class OverviewNeverOmits(unittest.TestCase):
    def test_every_board_meeting_surfaces_a_decision_or_a_gap(self):
        from macro.compute import events
        from macro.render.pages.overview import today_section

        for meeting in SCHEDULE:
            for days_after in (0, 1, 3, 7):
                now = datetime.combine(meeting + timedelta(days=days_after), time(18, 0),
                                       tzinfo=TAIPEI)
                for decision in (ok(meeting.isoformat()),
                                 {"status": "unavailable", "reason": "抓不到"},
                                 {"status": "unparsed", "date": meeting.isoformat(), "reason": "讀不出"},
                                 ok((meeting - timedelta(days=91)).isoformat())):
                    state = cbc_board.decision_status(decision, SCHEDULE, now)
                    html = today_section({"events": events.build(None, state, {}, [], now)})
                    self.assertIn('class="chg-tag">台灣央行', html,
                                  f"{meeting} +{days_after}d {decision.get('status')}")


class HistoricalWording(unittest.TestCase):
    """對抗性審查拿 2011 年起 61 份真實新聞稿跑出來、原本讀錯或讀不到的寫法。"""

    def test_reserve_ratio_with_the_verb_first_2022(self):
        text = (HOLD.replace("維持年息2%、2.375%及4.25%", "維持年息1.5%、1.875%及3.75%")
                + "三、本行理事會一致同意調升新台幣存款準備率0.25個百分點。"
                + "另調升新台幣活期性及定期性存款準備率各0.25個百分點(詳附件)，自本年10月1日起實施。")
        reserve = cbc.parse_board_decision(text, 2022)["reserve"]
        self.assertEqual(reserve, {"action": "raise", "step": 0.25, "effective": "2022-10-01"})

    def test_full_width_percent_2011(self):
        text = ("本行重貼現率、擔保放款融通利率及短期融通利率各調升0.125個百分點，分別由年息"
                "1.750％、2.125％及4％調整為年息1.875％、2.25％及4.125％，自本年7月1日起實施。")
        rate = cbc.parse_board_decision(text, 2011)["rate"]
        self.assertEqual((rate["action"], rate["from"], rate["to"], rate["effective"]),
                         ("raise", 1.75, 1.875, "2011-07-01"))

    def test_effective_date_in_the_lead_sentence_2016(self):
        text = ("三、本日本行理事會一致決議採行下列措施，並自本年3月25日起實施。(一) 本行重貼現率、"
                "擔保放款融通利率及短期融通利率各調降0.125個百分點，分別由年息1.625%、2%及3.875%"
                "調整為1.5%、1.875%及3.75%。四、本行將密切關注。")
        rate = cbc.parse_board_decision(text, 2016)["rate"]
        self.assertEqual(rate["effective"], "2016-03-25")

    def test_ltv_wordings(self):
        body = (HOLD + "修正「中央銀行對金融機構辦理不動產抵押貸款業務規定」，自本年3月19日起實施。"
                "(1) 第3戶購屋貸款最高成數，由6成降至5.5成。(2) 購地貸款最高成數降為5成，並保留1成動工款。"
                "業務聯繫單位：")
        changes = cbc.parse_board_decision(body, 2021)["credit"]["changes"]
        self.assertEqual(changes, ["第 3 戶以上購屋貸款成數上限 6 成 → 5.5 成",
                                   "購地貸款成數上限調為 5 成"])

    def test_notice_title_with_spacing(self):
        pages = {"u1": "發布日期：2026-09-17 " + SEPT_2026}
        items = [{"title": "中央銀行 理監事聯席會議決議新聞稿 ", "link": "u1"}]
        with mock.patch.object(cbc, "get", side_effect=lambda url, **_: pages[url]):
            self.assertEqual(cbc.latest_board_decision(items=items)["status"], "ok")

    def test_redirected_homepage_is_rejected_by_the_page_fetch(self):
        from macro.http import FetchError

        def fake_get(url, **kwargs):
            body = "<html>中央銀行首頁 最新消息</html>"
            if kwargs["validate"](body):
                return body
            raise FetchError("不合格")

        with mock.patch.object(cbc, "get", side_effect=fake_get):
            self.assertEqual(cbc._notice_text("https://www.cbc.gov.tw/tw/cp-302-1-x-1.html"), "")


class MoreStatus(unittest.TestCase):
    def test_unreadable_notice_on_an_unscheduled_date_is_missing(self):
        state = cbc_board.decision_status({"status": "unparsed", "date": "2026-10-15", "reason": "讀不出"},
                                          SCHEDULE, tpe(2026, 10, 15, 18))
        self.assertEqual((state["state"], state["meeting"]), ("missing", "2026-10-15"))

    def test_after_announcement_time_pending_is_overdue(self):
        state = cbc_board.decision_status(ok("2026-06-18"), SCHEDULE, tpe(2026, 9, 17, 17))
        self.assertEqual((state["state"], state["overdue"]), ("pending", True))

    def test_move_without_effective_date_says_why_it_was_not_patched(self):
        decision = {"status": "ok", "date": "2026-09-17",
                    "rate": {"action": "raise", "step": 0.125, "from": 2.0, "to": 2.125,
                             "effective": None}}
        _rate, result = cbc_board.reconcile_discount(Reconcile.RATE, decision)
        self.assertFalse(result["patched"])
        self.assertIn("讀不出生效日", result["reason"])


if __name__ == "__main__":
    unittest.main()
