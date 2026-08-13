"""FOMC 聲明切句與比對的測試。

切句錯了會把異議委員的名字拆成兩「句」，而異議票數是聲明裡最重要的
訊號之一——2026-07 那次從 12–0 變成 9–3，三票反對。
"""
import unittest

from macro.sources.fomc_text import _sentences, _vote, _word_diff

STATEMENT = (
    "The Committee decided to maintain the target range for the federal funds "
    "rate at 3-1/2 to 3-3/4 percent. "
    "Voting against the monetary policy action were Beth M. Hammack, "
    "Neel Kashkari, and Lorie K. Logan, who preferred to raise the target range "
    "by 1/4 percentage point at this meeting. "
    "Economic activity is expanding at a solid pace despite elevated uncertainty."
)


class TestSentences(unittest.TestCase):
    def test_initials_do_not_split(self):
        sents = _sentences(STATEMENT)
        joined = [s for s in sents if "Hammack" in s]
        self.assertEqual(len(joined), 1)
        self.assertIn("Beth M. Hammack", joined[0])
        self.assertIn("Lorie K. Logan", joined[0])

    def test_fraction_does_not_split(self):
        sents = _sentences(STATEMENT)
        target = [s for s in sents if "3-1/2" in s]
        self.assertEqual(len(target), 1)
        self.assertIn("3-3/4 percent", target[0])

    def test_count(self):
        self.assertEqual(len(_sentences(STATEMENT)), 3)


class TestVote(unittest.TestCase):
    def test_en_dash(self):
        self.assertEqual(_vote("approved by a 9 – 3 vote:"), "9–3")

    def test_unanimous(self):
        self.assertEqual(_vote("approved by a 12 - 0 vote:"), "12–0")

    def test_absent(self):
        self.assertEqual(_vote("no vote count here"), "")


class TestWordDiff(unittest.TestCase):
    def test_replacement(self):
        diff = _word_diff("The Committee reaffirmed its policy.",
                          "The Committee is continuing its policy.")
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0]["before"], "reaffirmed")
        self.assertEqual(diff[0]["after"], "is continuing")


if __name__ == "__main__":
    unittest.main()
