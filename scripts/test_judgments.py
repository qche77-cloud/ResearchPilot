import tempfile
import unittest
from pathlib import Path
from src.workbench import Workbench
from src.judgments import validate_proposal
from src.evidence_cards import cards
from src.stock_research import today, is_listing_source, update_brief
from src.agent import create_agent
from src.models import Source


class JudgmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.store.add_thesis('002837', '现金流改善', '财报', '现金流恶化')
        self.thesis = self.store.theses('002837')[0]
        self.snapshot = {'evidence': {'E1': {'title': '公告', 'url': 'https://example.com/notice',
                         'date': str(today()), 'text': '这是来自公告原文的逐字摘录内容。', 'read_status': 'success'}}, 'findings': []}

    def proposal(self):
        return {'before': self.thesis, 'verdict': '待核查', 'reason': '等待核对', 'quotes': [], 'gaps': '不足', 'snapshot': self.snapshot}

    def test_confirmation_preserves_previous_and_is_idempotent(self):
        p = self.proposal()
        pid = self.store.save_proposal('002837', self.thesis['id'], 'r', 'v', p)
        self.assertEqual(self.store.theses('002837')[0]['review'], '')
        self.assertEqual(pid, self.store.save_proposal('002837', self.thesis['id'], 'r', 'v', p))
        self.store.confirm_proposal(pid, '削弱', '用户自己的理由')
        self.assertEqual(self.store.theses('002837')[0]['status'], '观察中')
        versions = self.store.review_history(self.thesis['id'])
        self.assertEqual(versions[0]['before']['review'], '')
        self.assertIn('用户自己的理由', versions[0]['after']['review'])
        with self.assertRaises(ValueError):
            self.store.confirm_proposal(pid, '增强', '重复')
        self.assertEqual(len(self.store.review_history(self.thesis['id'])), 1)

    def test_stale_proposal_cannot_overwrite_manual_review(self):
        pid = self.store.save_proposal('002837', self.thesis['id'], 'r', 'v', self.proposal())
        self.store.review(self.thesis['id'], '新判断', '已结束')
        with self.assertRaises(ValueError):
            self.store.confirm_proposal(pid, '维持', '旧建议')
        self.assertEqual(self.store.theses('002837')[0]['review'], '新判断')

    def test_rejection_does_not_write_review(self):
        pid = self.store.save_proposal('002837', self.thesis['id'], 'r', 'v', self.proposal())
        self.store.reject_proposal(pid)
        self.assertEqual(self.store.review_history(self.thesis['id']), [])
        with self.assertRaises(ValueError):
            self.store.confirm_proposal(pid, '维持', '不能确认已拒绝建议')

    def test_cross_stock_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_proposal('000001', self.thesis['id'], 'r', 'v', self.proposal())

    def test_quotes_and_stale_dates(self):
        raw = {'verdict': '增强', 'reason': '有证据', 'supporting': [{'eid': 'E1', 'quote': '来自公告原文的逐字摘录'}], 'contrary': [], 'gaps': ''}
        self.assertEqual(validate_proposal(raw, self.snapshot)['verdict'], '增强')
        self.snapshot['evidence']['E1']['date'] = '2020-01-01'
        self.assertEqual(validate_proposal(raw, self.snapshot)['verdict'], '待核查')
        raw['supporting'][0]['quote'] = '这是一句虚构而非逐字引用的内容'
        with self.assertRaises(ValueError):
            validate_proposal(raw, self.snapshot)

    def test_listing_and_fallback_not_valid_judgment_evidence(self):
        raw = {'verdict': '增强', 'reason': '有证据', 'supporting': [{'eid': 'E1', 'quote': '来自公告原文的逐字摘录'}]}
        self.snapshot['evidence']['E1']['listing_page'] = True
        with self.assertRaises(ValueError):
            validate_proposal(raw, self.snapshot)
        self.assertTrue(is_listing_source('https://data.eastmoney.com/notices/stock/002837.html'))
        self.assertFalse(is_listing_source('https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=123'))

    def test_listing_not_new_announcement(self):
        s = create_agent('更新002837')
        s.diagnostics['agent']['baseline'] = {'as_of': '2020-01-01', 'urls': []}
        s.sources = [Source('新闻列表', 'https://data.eastmoney.com/notices/stock/002837.html', '', 'Web Result', 1, published_date=str(today()))]
        s.mark_completed()
        self.assertIn('未检索到', update_brief(s))

    def test_cards_exact_excerpt_and_legacy_fallback(self):
        self.snapshot['findings'] = [{'text': '分析', 'kind': 'inference', 'evidence_ids': ['E1'],
                                      'excerpts': [{'evidence_id': 'E1', 'text': '虚构摘录'}]}]
        self.assertIn('开头', cards(self.snapshot)[0]['excerpt_kind'])
        self.snapshot['findings'][0]['excerpts'][0]['text'] = '来自公告原文的逐字摘录'
        self.assertIn('逐字', cards(self.snapshot)[0]['excerpt_kind'])

    def test_confirmation_ui_requires_explicit_checkbox(self):
        from streamlit.testing.v1 import AppTest
        pid = self.store.save_proposal('002837', self.thesis['id'], 'r', 'v', self.proposal())
        source = ('from src.workbench import Workbench\nfrom src.storage import ResearchRunRepository\n'
                  'from src.judgment_ui import render_judgment\n'
                  f's=Workbench({str(self.store.path)!r})\nr=ResearchRunRepository({str(Path(self.tmp.name) / "runs.db")!r})\n'
                  'r.initialize()\nrender_judgment(s,r,"002837",s.theses("002837")[0])')
        app = AppTest.from_string(source).run(timeout=20)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == '确认并保存新版本').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.store.proposals('002837')[0]['status'], 'pending')
        # A real form submits its checkbox and button in one batch. Running the
        # app between editing and submitting discards unsubmitted form state in
        # newer AppTest versions and does not model the browser interaction.
        app.checkbox[0].check()
        next(b for b in app.button if b.label == '确认并保存新版本').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.store.proposals('002837')[0]['status'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
