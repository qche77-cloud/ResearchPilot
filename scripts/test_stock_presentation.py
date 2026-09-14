import unittest
from src.stock_presentation import search_directory, financial_summary
from src.stock_data import data_error_message
import requests


class StockPresentationTests(unittest.TestCase):
    def test_errors_are_actionable(self):
        self.assertIn('超时', data_error_message(requests.exceptions.Timeout()))
        self.assertIn('代理', data_error_message(requests.exceptions.ProxyError()))
        self.assertIn('校验', data_error_message(ValueError('untrusted raw message')))

    def test_search_name_and_code(self):
        rows = [{'symbol': '002837', 'name': '英维克'}, {'symbol': '000001', 'name': '平安银行'}]
        self.assertEqual(search_directory('英维', rows)[0]['symbol'], '002837')
        self.assertEqual(search_directory('000001', rows)[0]['name'], '平安银行')
        self.assertEqual(search_directory('不存在', rows), [])

    def test_units_period_and_duplicates(self):
        rows = [
            {'报告期': '20260630', 'item_title': '收入(万元)', 'item_value': '30000'},
            {'报告期': '20260630', 'item_title': '净利润', 'item_value': '100000000'},
            {'报告期': '20260630', 'item_title': '收入(万元)', 'item_value': '30000'},
            {'报告期': '20251231', 'item_title': '收入(万元)', 'item_value': '50000'},
        ]
        result = financial_summary(rows, '20260630')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['展示值'], '3.00')
        self.assertEqual(result[0]['单位'], '亿元')
        self.assertEqual(result[1]['展示值'], '100,000,000')
        self.assertEqual(result[1]['单位'], '单位待核对')

    def test_missing_negative_and_zero(self):
        rows = [{'报告期': '20260630', 'item_title': '现金流(元)', 'item_value': '-100000000'},
                {'报告期': '20260630', 'item_title': '每股(元/股)', 'item_value': '0'},
                {'报告期': '20260630', 'item_title': '缺失', 'item_value': None}]
        result = financial_summary(rows, '20260630')
        self.assertEqual(result[0]['展示值'], '-1.00')
        self.assertEqual(result[1]['展示值'], '0')
        self.assertEqual(len(result), 2)


if __name__ == '__main__':
    unittest.main()
